#!/usr/bin/env python3
"""Wspólne, bezpieczne operacje dla skilla walkthrough nieruchomości."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import stat
import sys
import tempfile
import unicodedata
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, Optional, Sequence, Union
from urllib.parse import urlsplit

try:
    import fcntl
except ImportError:  # pragma: no cover - niedostępne w natywnym runtime Windows.
    fcntl = None  # type: ignore

try:
    import msvcrt
except ImportError:  # pragma: no cover - dostępne wyłącznie w natywnym runtime Windows.
    msvcrt = None  # type: ignore


PathLike = Union[str, os.PathLike]
PROJECT_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
POLISH_ASCII_TRANSLATION = str.maketrans({"ł": "l", "Ł": "L"})
_PROJECT_LOCK_HELD: ContextVar[bool] = ContextVar(
    "property_walkthrough_project_lock_held", default=False
)


class ProjectStateError(ValueError):
    """Błąd bezpiecznego odczytu albo zapisu stanu projektu."""


class ProjectStatePostCommitError(ProjectStateError):
    """Stan został opublikowany, ale nie potwierdzono trwałości katalogu."""

    def __init__(self, destination: PathLike, message: str) -> None:
        super().__init__(message)
        self.destination = Path(destination)
        self.committed = True
        self.published = True


def configure_utf8_stdio() -> None:
    """Ustaw stabilne UTF-8 dla wyjścia CLI na macOS i Windows."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="strict")
            except (OSError, ValueError):
                # Strumienie zastępcze używane przez hosta mogą nie pozwalać
                # na rekonfigurację. Wtedy zachowujemy ustawienia hosta.
                pass


class PolishArgumentParser(argparse.ArgumentParser):
    """ArgumentParser z pełną, stabilną pomocą po polsku."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        add_help = kwargs.pop("add_help", True)
        super().__init__(*args, add_help=False, **kwargs)
        self._positionals.title = "argumenty pozycyjne"
        self._optionals.title = "opcje"
        if add_help:
            self.add_argument(
                "-h",
                "--help",
                action="help",
                help="Pokaż tę pomoc i zakończ.",
            )

    @staticmethod
    def _translate_labels(text: str) -> str:
        lines = []
        for line in text.splitlines(keepends=True):
            if line.startswith("usage: "):
                line = "użycie: " + line[len("usage: ") :]
            lines.append(line)
        return "".join(lines).replace("optional arguments:", "opcje:")

    def format_usage(self) -> str:
        return self._translate_labels(super().format_usage())

    def format_help(self) -> str:
        return self._translate_labels(super().format_help())

    def parse_args(
        self,
        args: Optional[Sequence[str]] = None,
        namespace: Optional[argparse.Namespace] = None,
    ) -> argparse.Namespace:
        """Parsuj argumenty po ustaleniu kodowania strumieni polecenia."""

        configure_utf8_stdio()
        return super().parse_args(args, namespace)


def utc_now() -> str:
    """Zwróć bieżący czas UTC w stabilnym formacie ISO 8601."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def safe_slug(value: str, max_length: int = 64) -> str:
    """Zamień nazwę na bezpieczny slug ASCII bez elementów ścieżki.

    Funkcja służy do tworzenia nowych identyfikatorów. Do sprawdzania już
    istniejącego identyfikatora użyj :func:`validate_project_id`.
    """

    if not isinstance(value, str):
        raise ProjectStateError("Nazwa slugu musi być tekstem.")
    if isinstance(max_length, bool) or not isinstance(max_length, int) or max_length < 1:
        raise ProjectStateError("Maksymalna długość slugu musi być dodatnią liczbą całkowitą.")

    normalized = unicodedata.normalize("NFKD", value.strip().translate(POLISH_ASCII_TRANSLATION))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")
    slug = slug[:max_length].rstrip("-")

    if not slug:
        raise ProjectStateError("Nie można utworzyć bezpiecznego slugu z podanej nazwy.")
    validate_project_id(slug, max_length=max_length)
    return slug


def validate_project_id(value: str, max_length: int = 64) -> str:
    """Sprawdź identyfikator projektu i zwróć go bez modyfikacji."""

    if not isinstance(value, str):
        raise ProjectStateError("Identyfikator projektu musi być tekstem.")
    if not value or len(value) > max_length:
        raise ProjectStateError(
            f"Identyfikator projektu musi mieć od 1 do {max_length} znaków."
        )
    if not PROJECT_ID_PATTERN.fullmatch(value):
        raise ProjectStateError(
            "Identyfikator projektu może zawierać tylko małe litery ASCII, "
            "cyfry i pojedyncze łączniki."
        )
    return value


def _path_is_within(path: Path, root: Path) -> bool:
    """Sprawdź relację ścieżek bez zależności od Path.is_relative_to."""

    return path == root or root in path.parents


def _normalized_managed_candidate(
    project_root: PathLike,
    candidate: PathLike,
) -> tuple[Path, Path, Path]:
    """Znormalizuj ścieżkę docelową bez rozwijania dowiązań po drodze."""

    root_input = Path(project_root).expanduser()
    if root_input.is_symlink():
        raise ProjectStateError("Katalog zarządzany nie może być dowiązaniem symbolicznym.")
    root = root_input.resolve(strict=False)
    if not root.exists() or not root.is_dir():
        raise ProjectStateError(f"Katalog zarządzany nie istnieje: {root}")
    candidate_input = Path(candidate).expanduser()
    combined = candidate_input if candidate_input.is_absolute() else root / candidate_input
    lexical = Path(os.path.abspath(str(combined)))
    if not _path_is_within(lexical, root):
        raise ProjectStateError("Ścieżka docelowa wychodzi poza katalog projektu.")
    return root, lexical, lexical.relative_to(root)


def _check_managed_directories(
    root: Path,
    parts: Sequence[str],
    *,
    create: bool,
) -> Path:
    """Sprawdź lub utwórz katalogi bez przechodzenia przez symlinki."""

    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ProjectStateError(
                f"Katalog docelowy nie może być dowiązaniem symbolicznym: {current}"
            )
        if current.exists():
            if not current.is_dir():
                raise ProjectStateError(
                    f"Element ścieżki docelowej nie jest katalogiem: {current}"
                )
            continue
        if not create:
            # Nieistniejąca reszta ścieżki nie może jeszcze zawierać symlinka.
            # Wywołujący może więc bezpiecznie zaplanować cel bez tworzenia
            # pustych katalogów przed właściwym etapem publikacji.
            break
        try:
            current.mkdir()
        except OSError as exc:
            raise ProjectStateError(
                f"Nie można utworzyć bezpiecznego katalogu {current}: {exc}"
            ) from exc
        if current.is_symlink() or not current.is_dir():
            raise ProjectStateError(
                f"Utworzony element nie jest bezpiecznym katalogiem: {current}"
            )
    return current


def resolve_managed_output_path(
    project_root: PathLike,
    candidate: PathLike,
    *,
    create_parent: bool = False,
    must_exist: bool = False,
) -> Path:
    """Rozwiąż ścieżkę zapisu bez wyjścia przez symlink katalogu nadrzędnego.

    Funkcja łączy kontrolę leksykalnej granicy projektu, kontrolę każdego
    istniejącego katalogu nadrzędnego i kontrolę granicy po rozwinięciu ścieżki.
    Dzięki temu wszystkie skrypty publikujące artefakty stosują ten sam kontrakt.
    """

    root, lexical, relative = _normalized_managed_candidate(project_root, candidate)
    _check_managed_directories(root, relative.parts[:-1], create=create_parent)
    if lexical.is_symlink():
        raise ProjectStateError(
            f"Plik docelowy nie może być dowiązaniem symbolicznym: {lexical}"
        )
    resolved = lexical.resolve(strict=False)
    if not _path_is_within(resolved, root):
        raise ProjectStateError("Ścieżka docelowa wychodzi poza katalog projektu.")
    if must_exist and not lexical.exists():
        raise ProjectStateError(f"Wymagana ścieżka nie istnieje: {lexical}")
    return lexical


def ensure_managed_directory(project_root: PathLike, candidate: PathLike) -> Path:
    """Utwórz katalog projektu po bezpiecznej, niesymlinkowanej ścieżce."""

    root, lexical, relative = _normalized_managed_candidate(project_root, candidate)
    directory = _check_managed_directories(root, relative.parts, create=True)
    if directory.resolve(strict=True) != lexical:
        raise ProjectStateError("Katalog docelowy nie rozwiązuje się wewnątrz projektu.")
    return directory


def validate_public_http_url(value: str, *, https_only: bool = False) -> str:
    """Sprawdź publiczny URL bez sieci i odrzuć lokalne reprezentacje hosta.

    Walidacja jest celowo syntaktyczna. Nie wykonuje DNS, nie śledzi przekierowań
    i nie obiecuje, że zdalny host pozostanie publiczny w chwili użycia.
    """

    if (
        not isinstance(value, str)
        or not value
        or len(value) > 4096
        or value != value.strip()
    ):
        raise ProjectStateError("URL musi być niepustym tekstem bez spacji brzegowych.")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ProjectStateError("URL zawiera niedozwolone znaki sterujące.")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ProjectStateError(f"URL ma niepoprawną składnię: {exc}") from exc

    allowed_schemes = {"https"} if https_only else {"http", "https"}
    if parsed.scheme.casefold() not in allowed_schemes or not parsed.hostname:
        expected = "HTTPS" if https_only else "HTTP albo HTTPS"
        raise ProjectStateError(f"URL musi być publicznym adresem {expected}.")
    if parsed.username is not None or parsed.password is not None:
        raise ProjectStateError("URL nie może zawierać danych logowania.")
    if parsed.fragment:
        raise ProjectStateError("URL nie może zawierać fragmentu.")
    if port is not None and not (1 <= port <= 65535):
        raise ProjectStateError("URL zawiera port spoza dozwolonego zakresu.")

    hostname = parsed.hostname.casefold().rstrip(".")
    if hostname != parsed.hostname.casefold():
        raise ProjectStateError("URL nie może używać hosta zakończonego kropką.")
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ProjectStateError("URL nie może wskazywać hosta lokalnego.")
    local_use_suffixes = {
        "corp",
        "example",
        "home",
        "home.arpa",
        "internal",
        "invalid",
        "lan",
        "local",
        "localdomain",
        "onion",
        "test",
    }
    if "." not in hostname or any(
        hostname == suffix or hostname.endswith("." + suffix)
        for suffix in local_use_suffixes
    ):
        raise ProjectStateError("URL nie może wskazywać hosta lokalnego ani intranetowego.")

    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None:
        if not address.is_global:
            raise ProjectStateError("URL nie może wskazywać niepublicznego adresu IP.")
    else:
        numeric_token = r"(?:0x[0-9a-f]+|[0-9]+)"
        if re.fullmatch(r"[0-9.]+", hostname) or re.fullmatch(
            rf"{numeric_token}(?:\.{numeric_token})*", hostname
        ):
            raise ProjectStateError("URL zawiera niekanoniczną liczbową postać hosta.")
        try:
            ascii_hostname = hostname.encode("idna").decode("ascii").casefold()
        except UnicodeError as exc:
            raise ProjectStateError("URL zawiera niepoprawną nazwę hosta.") from exc
        labels = ascii_hostname.split(".")
        if len(ascii_hostname) > 253 or any(
            not label
            or len(label) > 63
            or re.fullmatch(r"[a-z0-9-]+", label) is None
            or label.startswith("-")
            or label.endswith("-")
            for label in labels
        ):
            raise ProjectStateError("URL zawiera niepoprawne etykiety nazwy hosta.")
    return value


def resolve_project_path(
    project_root: PathLike,
    candidate: PathLike,
    must_exist: bool = False,
) -> Path:
    """Rozwiąż ścieżkę i odrzuć wyjście poza katalog projektu.

    Istniejące dowiązania symboliczne są rozwijane przed kontrolą granicy.
    Ścieżka absolutna jest dozwolona wyłącznie wtedy, gdy nadal leży wewnątrz
    katalogu projektu.
    """

    root_input = Path(project_root).expanduser()
    if root_input.is_symlink():
        raise ProjectStateError("Katalog projektu nie może być dowiązaniem symbolicznym.")
    root = root_input.resolve(strict=False)

    candidate_input = Path(candidate).expanduser()
    combined = candidate_input if candidate_input.is_absolute() else root / candidate_input
    resolved = combined.resolve(strict=False)

    if not _path_is_within(resolved, root):
        raise ProjectStateError("Ścieżka wychodzi poza katalog projektu.")
    if must_exist and not resolved.exists():
        raise ProjectStateError(f"Wymagana ścieżka nie istnieje: {resolved}")
    return resolved


def validate_project_root(project_root: PathLike, must_exist: bool = True) -> Path:
    """Sprawdź katalog projektu i jego bezpieczny identyfikator."""

    root_input = Path(project_root).expanduser()
    if root_input.is_symlink():
        raise ProjectStateError("Katalog projektu nie może być dowiązaniem symbolicznym.")
    root = root_input.resolve(strict=False)
    validate_project_id(root.name)
    if must_exist:
        if not root.exists():
            raise ProjectStateError(f"Katalog projektu nie istnieje: {root}")
        if not root.is_dir():
            raise ProjectStateError(f"Ścieżka projektu nie jest katalogiem: {root}")
    return root


@contextmanager
def exclusive_project_lock(project_root: PathLike) -> Iterator[None]:
    """Zablokuj modyfikacje manifestu projektu na czas całej transakcji.

    Natywna blokada systemu obejmuje pełne read-check-validate-write. Plik
    blokady pozostaje w katalogu projektu i nie zawiera danych użytkownika.
    """

    root = validate_project_root(project_root)
    if _PROJECT_LOCK_HELD.get():
        raise ProjectStateError("Zagnieżdżona blokada manifestu projektu jest niedozwolona.")
    if fcntl is None and msvcrt is None:
        raise ProjectStateError(
            "Runtime nie udostępnia natywnej blokady plikowej wymaganej przez projekt."
        )
    lock_path = root / ".project.lock"
    if lock_path.is_symlink():
        raise ProjectStateError("Plik blokady projektu nie może być dowiązaniem symbolicznym.")

    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    try:
        descriptor = os.open(str(lock_path), flags, 0o600)
    except OSError as exc:
        raise ProjectStateError(f"Nie można otworzyć blokady projektu: {exc}") from exc

    locked = False
    lock_token = None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ProjectStateError("Plik blokady projektu nie jest zwykłym plikiem.")
        try:
            if fcntl is not None:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
            else:
                if os.fstat(descriptor).st_size == 0:
                    os.write(descriptor, b"\0")
                    os.fsync(descriptor)
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
            locked = True
            lock_token = _PROJECT_LOCK_HELD.set(True)
        except OSError as exc:
            raise ProjectStateError(f"Nie można zablokować projektu: {exc}") from exc
        try:
            yield
        finally:
            if locked:
                try:
                    if fcntl is not None:
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
                    else:
                        os.lseek(descriptor, 0, os.SEEK_SET)
                        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            if lock_token is not None:
                _PROJECT_LOCK_HELD.reset(lock_token)
    finally:
        os.close(descriptor)


def locked_project_mutation(function: Callable[..., Any]) -> Callable[..., Any]:
    """Obejmij istniejący entrypoint modyfikujący pełną blokadą projektu."""

    @wraps(function)
    def wrapper(project_root: PathLike, *args: Any, **kwargs: Any) -> Any:
        root = validate_project_root(project_root)
        with exclusive_project_lock(root):
            return function(root, *args, **kwargs)

    return wrapper


def _reject_duplicate_keys(pairs: Iterable[tuple]) -> Dict[str, Any]:
    """Zbuduj obiekt JSON, odrzucając niejednoznaczne duplikaty kluczy."""

    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProjectStateError(f"Plik JSON zawiera powtórzony klucz: {key}")
        result[key] = value
    return result


def load_json(path: PathLike) -> Any:
    """Wczytaj plik JSON jako UTF-8 i odrzuć duplikaty kluczy."""

    json_path = Path(path)
    if json_path.is_symlink():
        raise ProjectStateError(f"Plik JSON nie może być dowiązaniem symbolicznym: {json_path}")
    try:
        with json_path.open("r", encoding="utf-8") as handle:
            return json.load(handle, object_pairs_hook=_reject_duplicate_keys)
    except ProjectStateError:
        raise
    except json.JSONDecodeError as exc:
        raise ProjectStateError(
            f"Niepoprawny JSON w pliku {json_path}: wiersz {exc.lineno}, "
            f"kolumna {exc.colno}."
        ) from exc
    except UnicodeDecodeError as exc:
        raise ProjectStateError(f"Plik nie jest poprawnym UTF-8: {json_path}") from exc
    except OSError as exc:
        raise ProjectStateError(f"Nie można odczytać pliku JSON {json_path}: {exc}") from exc


def _fsync_directory(directory: Path) -> None:
    """Utrwal metadane katalogu, jeżeli system to obsługuje."""

    if os.name == "nt":
        return

    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        descriptor = os.open(str(directory), flags)
    except OSError as exc:
        raise ProjectStateError(
            f"Nie można otworzyć katalogu do utrwalenia: {directory}: {exc}"
        ) from exc
    try:
        os.fsync(descriptor)
    except OSError as exc:
        raise ProjectStateError(
            f"Nie można utrwalić katalogu po zapisie: {directory}: {exc}"
        ) from exc
    finally:
        os.close(descriptor)


def atomic_write_json(path: PathLike, data: Any) -> None:
    """Zapisz JSON atomowo przez plik tymczasowy na tym samym filesystemie.

    Dane są kodowane jako UTF-8, plik jest synchronizowany przez ``fsync``,
    publikowany przez ``os.replace``, a następnie synchronizowany jest katalog
    nadrzędny. Niedokończony plik tymczasowy jest usuwany po błędzie.
    """

    destination = Path(path)
    if destination.exists() and destination.is_symlink():
        raise ProjectStateError(
            f"Plik docelowy nie może być dowiązaniem symbolicznym: {destination}"
        )
    try:
        serialized = json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ) + "\n"
    except (TypeError, ValueError) as exc:
        raise ProjectStateError(f"Danych nie można zapisać jako poprawny JSON: {exc}") from exc

    parent = destination.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ProjectStateError(f"Nie można utworzyć katalogu {parent}: {exc}") from exc

    descriptor = -1
    temporary_name = ""
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=str(parent)
        )
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            descriptor = -1
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
        temporary_name = ""
        try:
            _fsync_directory(parent)
        except (OSError, ProjectStateError) as exc:
            raise ProjectStatePostCommitError(
                destination,
                f"Plik {destination} został opublikowany, ale nie udało się "
                "potwierdzić trwałości katalogu nadrzędnego.",
            ) from exc
    except ProjectStatePostCommitError:
        raise
    except OSError as exc:
        raise ProjectStateError(f"Nie udało się atomowo zapisać {destination}: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_name:
            try:
                os.unlink(temporary_name)
            except OSError:
                temporary_name = ""


def sha256_file(path: PathLike, chunk_size: int = 1024 * 1024) -> str:
    """Oblicz małymi porcjami SHA-256 zwykłego pliku."""

    file_path = Path(path)
    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size < 1:
        raise ProjectStateError("Rozmiar porcji SHA-256 musi być dodatnią liczbą całkowitą.")
    if file_path.is_symlink():
        raise ProjectStateError(f"Nie można haszować dowiązania symbolicznego: {file_path}")
    if not file_path.is_file():
        raise ProjectStateError(f"Nie można haszować ścieżki, która nie jest plikiem: {file_path}")

    digest = hashlib.sha256()
    try:
        with file_path.open("rb") as handle:
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError as exc:
        raise ProjectStateError(f"Nie można obliczyć SHA-256 pliku {file_path}: {exc}") from exc
    return digest.hexdigest()


__all__ = [
    "PROJECT_ID_PATTERN",
    "POLISH_ASCII_TRANSLATION",
    "SHA256_PATTERN",
    "ProjectStateError",
    "atomic_write_json",
    "ensure_managed_directory",
    "load_json",
    "resolve_managed_output_path",
    "resolve_project_path",
    "safe_slug",
    "sha256_file",
    "utc_now",
    "validate_public_http_url",
    "validate_project_id",
    "validate_project_root",
]
