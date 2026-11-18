# CNIL reference: source record

| Field | Value |
|---|---|
| Title | L'anonymisation de données personnelles |
| Publisher | Commission nationale de l'informatique et des libertés (CNIL) |
| URL | https://www.cnil.fr/fr/technologies/lanonymisation-de-donnees-personnelles |
| Date shown on the page | 19 mai 2020 (no update date shown) |
| Retrieved | 2026-11-16 |
| Retrieval method | `python tools/cnil_source.py` (HTTP GET, HTML of the `<main>` element, tags removed, whitespace collapsed) |
| Normalised SHA-256 | `15c098cc374c4b3b709904dd3004236fed3f34ed2a6eca349e5f479fb6d32cbc` |
| Normalised length | 8261 characters |
| Review interval | 180 days (next review by 2027-05-15) |
| Drift status | none recorded |

The page text is not stored in this repository. Its reuse licence has not been checked, so only this record, short quotations and our own interpretation are committed (decision F2).

## Sections of the page

1. Qu'est-ce que l'anonymisation ?
2. Pourquoi anonymiser des données personnelles ?
3. Comment anonymiser tout en préservant au maximum l'utilité du jeu de données ?
4. Comment vérifier l'efficacité de l'anonymisation ?
5. Comment se prémunir des risques liés à l'anonymisation ?
6. Les textes de référence

## Texts the page refers to

| Text | Status here |
|---|---|
| G29 / WP29, Avis 05/2014 sur les techniques d'anonymisation (WP216) | **Not ingested.** Nothing in this repository relies on its content. Open finding F-002. |
| Code des relations entre le public et l'administration, art. L312-1-2 | Not read. Out of scope for the product. |

## How to refresh

1. A person runs `python tools/cnil_source.py --check` (needs network; it is never run by the product or by the gate).
2. If the hash differs, the person reads the page, records what changed, and only then updates this file and `requirements.yaml`.
3. Affected rows of `../rtm.yaml` are re-assessed.

The hash above was computed in the development session of 2026-11-16. Interpretations in `requirements.yaml` were written from a full read of the page made on 2026-11-12 and were not re-read against the page on 2026-11-16; the six section titles and eight key terms were checked on that date.
