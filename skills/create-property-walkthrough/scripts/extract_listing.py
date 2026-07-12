#!/usr/bin/env python3
"""Wyodrębnianie danych ogłoszenia wyłącznie z lokalnego snapshotu HTML.

Helper nie pobiera stron, nie rozwiązuje DNS i nie otwiera socketów. Snapshot
jest nieufnym zbiorem danych: parser odczytuje JSON-LD, Open Graph oraz jawne
publiczne URL-e obrazów z HTML, które zaufana powierzchnia może później pobrać.
"""

from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union
from urllib.parse import urljoin, urlsplit

try:
    from _common import PolishArgumentParser, atomic_write_json, sha256_file
except ImportError:  # Bezpieczny fallback dla izolowanego uruchomienia helpera.
    import hashlib
    import tempfile

    PolishArgumentParser = argparse.ArgumentParser

    def sha256_file(path: Union[os.PathLike[str], str]) -> str:
        """Oblicz lokalnie SHA-256, gdy moduł projektu nie jest jeszcze dostępny."""

        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def atomic_write_json(path: Union[os.PathLike[str], str], data: Any) -> None:
        """Zapisz JSON atomowo, gdy moduł projektu nie jest jeszcze dostępny."""

        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=".{}-".format(destination.name), dir=str(destination.parent)
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


DEFAULT_MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_TAGS = 100_000
DEFAULT_MAX_JSON_LD_BLOCKS = 32
DEFAULT_MAX_JSON_LD_CHARS = 512 * 1024
DEFAULT_MAX_JSON_NODES = 20_000

LISTING_FIELDS = (
    "title",
    "location",
    "price",
    "area",
    "rooms",
    "floor",
    "property_type",
    "description",
)


class ListingExtractionError(ValueError):
    """Błąd bezpiecznego odczytu lokalnego snapshotu ogłoszenia."""


def validate_http_url(value: str) -> str:
    """Zweryfikuj publiczny URL HTTP/HTTPS bez wykonywania połączenia.

    Walidacja odrzuca dane logowania, fragmenty, localhost oraz literalne adresy
    prywatne i specjalne. Ochrona DNS i redirectów należy do zaufanej
    powierzchni, która zapisuje snapshot.
    """

    if not isinstance(value, str) or not value or value != value.strip():
        raise ListingExtractionError("URL musi być niepustym tekstem bez skrajnych spacji.")
    if len(value) > 4096 or any(ord(character) < 32 for character in value):
        raise ListingExtractionError("URL jest zbyt długi albo zawiera znaki sterujące.")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ListingExtractionError("URL ma nieprawidłową składnię.") from exc
    if parsed.scheme.casefold() not in {"http", "https"}:
        raise ListingExtractionError("Dozwolone są wyłącznie adresy HTTP i HTTPS.")
    if not parsed.netloc or not hostname:
        raise ListingExtractionError("URL musi zawierać nazwę hosta.")
    if parsed.username is not None or parsed.password is not None:
        raise ListingExtractionError("URL provenance nie może zawierać danych logowania.")
    if parsed.fragment:
        raise ListingExtractionError("URL provenance nie może zawierać fragmentu.")
    if port is not None and not 1 <= port <= 65535:
        raise ListingExtractionError("Port URL jest poza dozwolonym zakresem.")

    normalized_host = hostname.rstrip(".").casefold()
    if normalized_host == "localhost" or normalized_host.endswith(".localhost"):
        raise ListingExtractionError("Lokalny host nie jest dozwolony jako provenance.")
    try:
        address = ipaddress.ip_address(normalized_host.strip("[]"))
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ListingExtractionError("Prywatny lub specjalny adres IP nie jest dozwolony.")
    return value


class _SnapshotParser(HTMLParser):
    """Ograniczony parser zbierający tylko jawne metadane i URL-e obrazów."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.open_graph: Dict[str, List[str]] = {}
        self.html_image_candidates: List[Tuple[str, str]] = []
        self.json_ld_blocks: List[str] = []
        self._json_ld_buffer: Optional[List[str]] = None
        self._json_ld_chars = 0
        self._tag_count = 0

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        self._tag_count += 1
        if self._tag_count > DEFAULT_MAX_TAGS:
            raise ListingExtractionError("Snapshot zawiera zbyt wiele elementów HTML.")
        if len(attrs) > 128:
            raise ListingExtractionError("Element HTML zawiera zbyt wiele atrybutów.")
        lowered = tag.casefold()
        attributes = {
            key.casefold(): value
            for key, value in attrs
            if isinstance(key, str) and value is not None
        }
        if lowered == "meta":
            name = (attributes.get("property") or attributes.get("name") or "").casefold()
            content = attributes.get("content")
            if name.startswith(("og:", "product:", "place:", "realestate:")) and content:
                if len(name) <= 200 and len(content) <= 50_000:
                    self.open_graph.setdefault(name, []).append(content)
            elif name in {"twitter:image", "twitter:image:src"} and content:
                self._add_image_candidate(content, "{}.content".format(name))
        elif lowered == "img":
            for key in ("src", "data-src", "data-original", "data-lazy-src"):
                self._add_image_candidate(attributes.get(key), "img.{}".format(key))
            for key in ("srcset", "data-srcset"):
                self._add_srcset_candidates(attributes.get(key), "img.{}".format(key))
        elif lowered == "source":
            for key in ("srcset", "data-srcset"):
                self._add_srcset_candidates(attributes.get(key), "source.{}".format(key))
        elif lowered == "link":
            rel = " ".join(attributes.get("rel", "").casefold().split())
            as_value = attributes.get("as", "").casefold()
            if rel == "image_src" or (rel in {"preload", "prefetch"} and as_value == "image"):
                self._add_image_candidate(attributes.get("href"), "link.href")
        elif lowered == "script":
            content_type = (attributes.get("type") or "").split(";", 1)[0].strip().casefold()
            if content_type == "application/ld+json":
                if self._json_ld_buffer is not None:
                    raise ListingExtractionError("Snapshot zawiera zagnieżdżony blok JSON-LD.")
                if len(self.json_ld_blocks) >= DEFAULT_MAX_JSON_LD_BLOCKS:
                    raise ListingExtractionError("Snapshot zawiera zbyt wiele bloków JSON-LD.")
                self._json_ld_buffer = []
                self._json_ld_chars = 0

    def _add_image_candidate(self, value: Optional[str], path: str) -> None:
        if not isinstance(value, str):
            return
        candidate = re.sub(r"\s+", " ", value).strip()
        if not candidate or len(candidate) > 4096:
            return
        self.html_image_candidates.append((candidate, path))

    def _add_srcset_candidates(self, value: Optional[str], path: str) -> None:
        if not isinstance(value, str) or len(value) > 20_000:
            return
        for index, item in enumerate(value.split(",")):
            candidate = item.strip().split()
            if candidate:
                self._add_image_candidate(candidate[0], "{}[{}]".format(path, index))

    def handle_data(self, data: str) -> None:
        if self._json_ld_buffer is None:
            return
        self._json_ld_chars += len(data)
        if self._json_ld_chars > DEFAULT_MAX_JSON_LD_CHARS:
            raise ListingExtractionError("Blok JSON-LD przekracza bezpieczny limit.")
        self._json_ld_buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "script" and self._json_ld_buffer is not None:
            self.json_ld_blocks.append("".join(self._json_ld_buffer))
            self._json_ld_buffer = None
            self._json_ld_chars = 0

    def close(self) -> None:
        super().close()
        if self._json_ld_buffer is not None:
            raise ListingExtractionError("Snapshot zawiera niedomknięty blok JSON-LD.")


def _reject_duplicate_keys(pairs: Iterable[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ListingExtractionError(
                "JSON-LD zawiera powtórzony klucz: {}".format(str(key)[:200])
            )
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ListingExtractionError("JSON-LD zawiera niedozwoloną stałą: {}".format(value))


def _load_json_ld(text: str, block_index: int) -> Any:
    stripped = text.strip()
    if not stripped:
        raise ListingExtractionError("Blok JSON-LD {} jest pusty.".format(block_index))
    try:
        return json.loads(
            stripped,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except ListingExtractionError:
        raise
    except json.JSONDecodeError as exc:
        raise ListingExtractionError(
            "Blok JSON-LD {} ma nieprawidłowy JSON: wiersz {}, kolumna {}.".format(
                block_index, exc.lineno, exc.colno
            )
        ) from exc


def _walk_nodes(value: Any) -> List[Tuple[Dict[str, Any], str]]:
    nodes: List[Tuple[Dict[str, Any], str]] = []
    stack: List[Tuple[Any, str, int]] = [(value, "$", 0)]
    visited = 0
    while stack:
        current, path, depth = stack.pop()
        visited += 1
        if visited > DEFAULT_MAX_JSON_NODES:
            raise ListingExtractionError("JSON-LD zawiera zbyt wiele węzłów.")
        if depth > 64:
            raise ListingExtractionError("JSON-LD jest zbyt głęboko zagnieżdżony.")
        if isinstance(current, dict):
            nodes.append((current, path[:500]))
            items = list(current.items())
            for key, child in reversed(items):
                if isinstance(child, (dict, list)):
                    safe_key = key if isinstance(key, str) and len(key) <= 80 else "?"
                    stack.append((child, "{}.{}".format(path, safe_key), depth + 1))
        elif isinstance(current, list):
            for index in range(len(current) - 1, -1, -1):
                child = current[index]
                if isinstance(child, (dict, list)):
                    stack.append((child, "{}[{}]".format(path, index), depth + 1))
    return nodes


def _node_score(node: Dict[str, Any]) -> int:
    raw_types = node.get("@type", [])
    types = raw_types if isinstance(raw_types, list) else [raw_types]
    type_text = " ".join(str(item).casefold() for item in types if isinstance(item, str))
    score = 0
    for marker in (
        "realestatelisting",
        "apartment",
        "house",
        "residence",
        "accommodation",
        "singlefamilyresidence",
    ):
        if marker in type_text:
            score += 20
    for key in ("address", "floorSize", "numberOfRooms", "offers", "image"):
        if key in node:
            score += 2
    return score


def _bounded_scalar(value: Any, *, max_length: int) -> Optional[Any]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        cleaned = re.sub(r"\s+", " ", value).strip()
        return cleaned[:max_length] if cleaned else None
    return None


def _address_text(value: Any) -> Optional[str]:
    if isinstance(value, str):
        scalar = _bounded_scalar(value, max_length=1000)
        return scalar if isinstance(scalar, str) else None
    if not isinstance(value, dict):
        return None
    parts: List[str] = []
    for key in (
        "streetAddress",
        "postalCode",
        "addressLocality",
        "addressRegion",
        "addressCountry",
    ):
        part = _bounded_scalar(value.get(key), max_length=300)
        if isinstance(part, str) and part not in parts:
            parts.append(part)
    return ", ".join(parts) if parts else None


def _nested_scalar(node: Dict[str, Any], keys: Sequence[str], *, max_length: int) -> Tuple[Optional[Any], str]:
    current: Any = node
    traversed: List[str] = []
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None, ""
        current = current[key]
        traversed.append(key)
    if isinstance(current, dict):
        for value_key in ("value", "amount", "name"):
            scalar = _bounded_scalar(current.get(value_key), max_length=max_length)
            if scalar is not None:
                return scalar, ".".join(traversed + [value_key])
        return None, ""
    return _bounded_scalar(current, max_length=max_length), ".".join(traversed)


def _image_urls(value: Any) -> List[str]:
    candidates: List[Any]
    if isinstance(value, list):
        candidates = value
    else:
        candidates = [value]
    result: List[str] = []
    for candidate in candidates:
        if isinstance(candidate, dict):
            candidate = candidate.get("contentUrl") or candidate.get("url")
        if not isinstance(candidate, str):
            continue
        try:
            validated = validate_http_url(candidate)
        except ListingExtractionError:
            continue
        if validated not in result:
            result.append(validated)
    return result


def _html_image_urls(
    candidates: Sequence[Tuple[str, str]], base_url: Optional[str]
) -> List[Tuple[str, str]]:
    """Znormalizuj jawne URL-e obrazów z HTML bez wykonywania połączeń sieciowych."""

    result: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for raw, path in candidates:
        parsed = urlsplit(raw)
        if parsed.scheme and parsed.scheme.casefold() not in {"http", "https"}:
            continue
        if not parsed.scheme and not base_url:
            continue
        candidate = urljoin(base_url, raw) if not parsed.scheme else raw
        try:
            validated = validate_http_url(candidate)
        except ListingExtractionError:
            continue
        if validated in seen:
            continue
        seen.add(validated)
        result.append((validated, path))
    return result


class _Accumulator:
    def __init__(self) -> None:
        self.listing: Dict[str, Any] = {field: None for field in LISTING_FIELDS}
        self.listing["images"] = []
        self.provenance: Dict[str, List[Dict[str, str]]] = {
            field: [] for field in LISTING_FIELDS + ("images",)
        }

    def set(self, field: str, value: Any, *, source: str, path: str) -> None:
        if value is None or self.listing[field] is not None:
            return
        self.listing[field] = value
        self.provenance[field].append({"source": source, "path": path[:500]})

    def add_images(self, values: Sequence[str], *, source: str, path: str) -> None:
        images = self.listing["images"]
        for value in values:
            if value not in images:
                images.append(value)
                self.provenance["images"].append(
                    {"source": source, "path": path[:500]}
                )


def _consume_json_ld(accumulator: _Accumulator, block: Any, block_index: int) -> None:
    nodes = _walk_nodes(block)
    ranked = sorted(
        enumerate(nodes), key=lambda item: (-_node_score(item[1][0]), item[0])
    )
    for _, (node, node_path) in ranked:
        base = "json_ld[{}]{}".format(block_index, node_path)
        for key in ("name", "headline"):
            value = _bounded_scalar(node.get(key), max_length=500)
            if value is not None:
                accumulator.set("title", value, source="json_ld", path="{}.{}".format(base, key))
                break
        value = _bounded_scalar(node.get("description"), max_length=20_000)
        accumulator.set("description", value, source="json_ld", path="{}.description".format(base))

        location = _address_text(node.get("address") or node.get("location"))
        accumulator.set("location", location, source="json_ld", path="{}.address".format(base))

        for keys in (("offers", "price"), ("price",)):
            value, suffix = _nested_scalar(node, keys, max_length=200)
            if value is not None:
                accumulator.set("price", value, source="json_ld", path="{}.{}".format(base, suffix))
                break
        for keys in (("floorSize",), ("usableArea",), ("area",)):
            value, suffix = _nested_scalar(node, keys, max_length=100)
            if value is not None:
                accumulator.set("area", value, source="json_ld", path="{}.{}".format(base, suffix))
                break
        for key in ("numberOfRooms", "numberOfBedrooms"):
            value = _bounded_scalar(node.get(key), max_length=100)
            if value is not None:
                accumulator.set("rooms", value, source="json_ld", path="{}.{}".format(base, key))
                break
        for key in ("floorLevel", "floor"):
            value = _bounded_scalar(node.get(key), max_length=100)
            if value is not None:
                accumulator.set("floor", value, source="json_ld", path="{}.{}".format(base, key))
                break
        for key in ("additionalType", "accommodationCategory", "@type"):
            raw = node.get(key)
            if isinstance(raw, list):
                raw = next((entry for entry in raw if isinstance(entry, str)), None)
            value = _bounded_scalar(raw, max_length=200)
            if value is not None:
                accumulator.set(
                    "property_type", value, source="json_ld", path="{}.{}".format(base, key)
                )
                break
        for key in ("image", "photo", "photos"):
            accumulator.add_images(
                _image_urls(node.get(key)), source="json_ld", path="{}.{}".format(base, key)
            )


def _first(meta: Dict[str, List[str]], *names: str) -> Optional[str]:
    for name in names:
        values = meta.get(name, [])
        for value in values:
            cleaned = _bounded_scalar(value, max_length=20_000)
            if isinstance(cleaned, str):
                return cleaned
    return None


def _consume_open_graph(accumulator: _Accumulator, meta: Dict[str, List[str]]) -> None:
    mapping = {
        "title": ("og:title",),
        "description": ("og:description",),
        "price": ("product:price:amount",),
        "property_type": ("og:type", "realestate:type"),
        "location": (
            "realestate:location",
            "og:street-address",
            "og:locality",
            "place:location:address",
        ),
        "area": ("realestate:area",),
        "rooms": ("realestate:rooms",),
        "floor": ("realestate:floor",),
    }
    limits = {"title": 500, "description": 20_000, "location": 1000}
    for field, names in mapping.items():
        value = _first(meta, *names)
        if value is not None:
            accumulator.set(
                field,
                value[: limits.get(field, 200)],
                source="open_graph",
                path=next(name for name in names if meta.get(name)),
            )
    image_values: List[str] = []
    for name in ("og:image", "og:image:url", "og:image:secure_url"):
        for value in meta.get(name, []):
            image_values.extend(_image_urls(value))
    accumulator.add_images(image_values, source="open_graph", path="og:image")


def _consume_html_images(
    accumulator: _Accumulator, candidates: Sequence[Tuple[str, str]], base_url: Optional[str]
) -> None:
    for value, path in _html_image_urls(candidates, base_url):
        accumulator.add_images([value], source="html_image", path=path)


def _read_snapshot(path: Path, max_bytes: int) -> Tuple[str, int, str]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ListingExtractionError("Nie można odczytać snapshotu: {}".format(path)) from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise ListingExtractionError("Snapshot nie może być dowiązaniem symbolicznym.")
    if not stat.S_ISREG(metadata.st_mode):
        raise ListingExtractionError("Snapshot musi być zwykłym plikiem.")
    if metadata.st_size <= 0:
        raise ListingExtractionError("Snapshot jest pusty.")
    if metadata.st_size > max_bytes:
        raise ListingExtractionError("Snapshot przekracza limit {} bajtów.".format(max_bytes))
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ListingExtractionError("Nie można odczytać snapshotu.") from exc
    if len(raw) > max_bytes:
        raise ListingExtractionError("Snapshot urósł podczas odczytu i przekroczył limit.")
    try:
        text = raw.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise ListingExtractionError("Snapshot nie jest poprawnym UTF-8.") from exc
    if "\x00" in text:
        raise ListingExtractionError("Snapshot zawiera niedozwolony znak NUL.")
    return text, len(raw), hashlib.sha256(raw).hexdigest()


def extract_listing_snapshot(
    snapshot_path: Union[os.PathLike[str], str],
    canonical_url: Optional[str] = None,
    *,
    max_bytes: int = DEFAULT_MAX_SNAPSHOT_BYTES,
) -> Dict[str, Any]:
    """Wyodrębnij metadane z jednego ograniczonego lokalnego snapshotu HTML."""

    if max_bytes < 1024 or max_bytes > 16 * 1024 * 1024:
        raise ListingExtractionError("Limit snapshotu musi mieścić się od 1 KiB do 16 MiB.")
    validated_url = validate_http_url(canonical_url) if canonical_url else None
    snapshot_input = Path(snapshot_path)
    text, size_bytes, snapshot_sha256 = _read_snapshot(snapshot_input, max_bytes)
    snapshot = snapshot_input.resolve()

    parser = _SnapshotParser()
    try:
        parser.feed(text)
        parser.close()
    except ListingExtractionError:
        raise
    except Exception as exc:
        raise ListingExtractionError("Nie udało się bezpiecznie sparsować HTML.") from exc

    accumulator = _Accumulator()
    warnings: List[str] = []
    for index, block_text in enumerate(parser.json_ld_blocks):
        try:
            block = _load_json_ld(block_text, index)
            _consume_json_ld(accumulator, block, index)
        except ListingExtractionError as exc:
            warnings.append(str(exc))
    _consume_open_graph(accumulator, parser.open_graph)
    _consume_html_images(accumulator, parser.html_image_candidates, validated_url)

    present = sum(accumulator.listing[field] is not None for field in LISTING_FIELDS)
    if accumulator.listing["images"]:
        present += 1
    status = "ok" if present == len(LISTING_FIELDS) + 1 else "partial"
    if present == 0:
        warnings.append("Snapshot nie zawiera obsługiwanych metadanych JSON-LD ani Open Graph.")

    return {
        "schema_version": 1,
        "status": status,
        "listing": accumulator.listing,
        "provenance": accumulator.provenance,
        "source": {
            "canonical_url": validated_url,
            "domain": urlsplit(validated_url).hostname if validated_url else None,
            "snapshot_path": str(snapshot),
            "snapshot_sha256": snapshot_sha256,
            "snapshot_size_bytes": size_bytes,
            "network_access": False,
        },
        "warnings": warnings,
        "errors": [],
    }


def blocked_listing_record(canonical_url: str, reason: str) -> Dict[str, Any]:
    """Zapisz bezpieczny fallback po blokadzie na zaufanej powierzchni web."""

    validated_url = validate_http_url(canonical_url)
    if not isinstance(reason, str) or not reason.strip():
        raise ListingExtractionError("Powód blokady musi być niepustym tekstem.")
    bounded_reason = re.sub(r"\s+", " ", reason).strip()[:1000]
    listing = {field: None for field in LISTING_FIELDS}
    listing["images"] = []
    return {
        "schema_version": 1,
        "status": "blocked",
        "listing": listing,
        "provenance": {field: [] for field in LISTING_FIELDS + ("images",)},
        "source": {
            "canonical_url": validated_url,
            "domain": urlsplit(validated_url).hostname,
            "snapshot_path": None,
            "snapshot_sha256": None,
            "snapshot_size_bytes": None,
            "network_access": False,
        },
        "warnings": ["Dostęp do strony został zablokowany; wymagany jest upload zdjęć."],
        "errors": [bounded_reason],
    }


extract_listing = extract_listing_snapshot


def build_parser() -> argparse.ArgumentParser:
    """Zbuduj polski interfejs poleceń helpera."""

    parser = PolishArgumentParser(
        description="Odczytaj metadane ogłoszenia z lokalnej kopii strony bez dostępu do sieci."
    )
    parser.add_argument("snapshot", nargs="?", help="Lokalna kopia strony HTML w UTF-8.")
    parser.add_argument("--url", help="Zweryfikowany URL HTTP/HTTPS używany wyłącznie jako opis pochodzenia danych.")
    parser.add_argument(
        "--blocked-reason",
        help="Zapisz informację o nieudanym pobraniu przez zaufane narzędzie.",
    )
    parser.add_argument("--output", help="Opcjonalny plik JSON zapisywany atomowo.")
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=DEFAULT_MAX_SNAPSHOT_BYTES,
        help="Maksymalny rozmiar snapshotu w bajtach.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Uruchom parser CLI i wypisz deterministyczny JSON UTF-8."""

    args = build_parser().parse_args(argv)
    try:
        if args.blocked_reason is not None:
            if args.snapshot is not None:
                raise ListingExtractionError(
                    "Tryb blokady nie może jednocześnie przyjmować snapshotu."
                )
            if not args.url:
                raise ListingExtractionError("Tryb blokady wymaga parametru --url.")
            result = blocked_listing_record(args.url, args.blocked_reason)
        else:
            if args.snapshot is None:
                raise ListingExtractionError("Podaj lokalny snapshot albo --blocked-reason.")
            result = extract_listing_snapshot(
                args.snapshot, canonical_url=args.url, max_bytes=args.max_bytes
            )
        if args.output:
            atomic_write_json(args.output, result)
        else:
            json.dump(result, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
            sys.stdout.write("\n")
        return 0
    except (ListingExtractionError, OSError, ValueError) as exc:
        sys.stderr.write("Błąd ekstrakcji ogłoszenia: {}\n".format(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_MAX_SNAPSHOT_BYTES",
    "ListingExtractionError",
    "blocked_listing_record",
    "extract_listing",
    "extract_listing_snapshot",
    "validate_http_url",
]
