# Kontrakt promptu image-to-video

## Reguły

Twórz pełny, samodzielny prompt po angielsku dla każdej sceny. Nie odwołuj się do poprzedniego promptu. Używaj zdjęcia jako jedynego źródła wizualnej prawdy. Nie dodawaj osobnego generycznego negative promptu.

## Szablon

```text
Use the attached approved source frame for scene {{scene_id}} as the only visual source of truth.

Create exactly one controlled camera movement: {{camera_move}}, moving {{direction}} at {{speed}} speed over a distance of {{distance}}. Begin smoothly from stillness and end in a stable composition. Produce subtle, physically credible parallax only between planes already visible in the source frame.

Preserve exactly the source architecture, spatial geometry, framing logic, walls, doors, windows, floors, ceilings, fixed elements, furniture, decor, materials, object count, object placement, reflections, and lighting. Keep all straight architectural lines stable and keep every visible object present and unchanged throughout.

Duration: {{duration_seconds}} seconds.
Aspect ratio: {{aspect_ratio}}.

Do not add rooms, openings, doors, windows, objects, or unseen geometry. Do not remove or duplicate objects. No morphing, melting, bending, geometry drift, lighting drift, scene replacement, or reveal beyond the visible source frame. Do not redesign the room.
```

## Polskie metadane

Zapisz obok promptu:

- `id_sceny`,
- `typ_pomieszczenia`,
- `ruch_kamery`,
- `czas_trwania_s`,
- `format`,
- `status_generowania`,
- `status_kontroli_jakosci`.

Prompt, JSON shot list, Markdown shot list i opcjonalny CSV muszą zgadzać się co do źródła, duration, ratio i ruchu.
