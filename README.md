# Știri 3DExposed

Pagină cu știri „șmechere” (Tech, Mașini, Spațiu, Construcții, Viral) și un calendar **Upcoming**, pentru idei de video-uri 3D. Se actualizează singură din oră în oră, gratuit, cu GitHub Actions + GitHub Pages.

## Ce face
- `build.py` citește sursele, grupează știrile duplicate, dă un scor 0–100 și scrie pagina în `site/`.
- `config.yaml` – **tot ce poți modifica tu**: surse, cuvinte, ponderi.
- `template.html` – aspectul paginii.
- `.github/workflows/update.yml` – rularea automată.

## Cum schimb sursele și cuvintele
Deschide `config.yaml` (și direct pe GitHub: creionul ✏️ → modifici → **Commit changes**).
- **Surse:** secțiunea `surse`. Ștergi sau adaugi un bloc de 4 rânduri.
- **Cuvinte bune / rele:** `cuvinte_bune` și `cuvinte_rele`, în forma `cuvânt: puncte`.
- **Ponderi:** secțiunea `scor`.
- **Upcoming:** frazele căutate și lansările ignorate (ex. Starlink) sunt în `upcoming`.

Pe pagină, la fiecare știre, „De ce scorul ăsta” arată ce cuvinte au contat.

## Cum îl rulez pe calculatorul meu
```
pip install -r requirements.txt
python build.py
```
Apoi deschizi `site/index.html`.

## Cum îl opresc
Pe GitHub: **Actions → Actualizare stiri → „…” (dreapta sus) → Disable workflow**. Pornești la loc din același meniu.

## De știut
- Dacă o sursă pică, restul merge; numele ei apare jos pe pagină.
- GitHub oprește singur rulările automate după 60 de zile fără nicio modificare în proiect. Primești un email; apeși **Enable workflow** și merge mai departe.
- Nu există chei sau parole în proiect. Dacă va fi nevoie vreodată, se pun în **Settings → Secrets**, nu în cod.
