# CLAUDE.md (cron-consolidator)

Plugin Hermes Agent (second plugin de la candidature au hackathon, date limite 11/11/2026 13 h PST). Reprise du
chantier : `.work/HANDOFF-hackathon-hermes.md` à la racine du parc.

## Règles
- Lecture seule, toujours : le plugin n'écrit rien dans le profil et n'applique aucune fusion (pas d'option `--apply`).
- Aucun hook, outil ni middleware : seulement `register_command` et `register_cli_command`.
- Chaque modification passe `python -m pytest tests -q`, puis `hermes plugins validate .`.
- README, PR et textes publics en anglais ; commits en français, format conventionnel.
- Jamais de données réelles dans le dépôt : la démo vient de `tests/make_demo_profile.py` (noms et prompts inventés).
  Les profils Hermes de Théo (serveur Hostinger) se lisent par copie temporaire, supprimée après l'essai.
- `platforms:` du catalogue = ce qui est réellement testé.

## Pièges
- Le dossier du dépôt n'est pas importable (tiret) : les tests chargent le paquet sous `cron_consolidator`.
- Les grappes de « même minute » écartent les tâches à plus de 6 déclenchements par jour (`*/30` etc.) : sans cela
  un poller relie toutes les tâches en un seul groupe (constaté sur le profil réel).
- Sur le profil réel de Théo : 42 tâches actives, 30 sont des scripts (`no_agent`), un seul vrai candidat à la fusion.
  Ne pas promettre d'économie en tokens sans `usage_audit.jsonl` (il s'arrête au 28/10 sur ce serveur).
