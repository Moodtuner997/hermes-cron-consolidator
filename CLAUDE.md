# CLAUDE.md (cron-consolidator)

Plugin Hermes Agent (second plugin de la candidature au hackathon, date limite 11/11/2026 13 h PST). Reprise du
chantier : `.work/HANDOFF-hackathon-hermes.md` à la racine du parc.

## Règles
- Lecture seule, toujours : le plugin n'écrit rien dans le profil et n'applique aucune fusion (pas d'option `--apply`).
- Aucun hook, outil ni middleware : seulement `register_command` et `register_cli_command`.
- Chaque modification passe `python -m pytest tests -q` (29 tests, sans Hermes), `hermes plugins validate .`, puis
  `tests/e2e_hermes.py` avec l'interpréteur de Hermes (dans un `HERMES_HOME` jetable : un dossier avec `config.yaml` qui
  active le plugin et une copie du plugin). La CI (`.github/workflows/ci.yml`, runners GitHub : ce dépôt est public)
  fait les trois sur ubuntu, windows et macos-latest, Hermes v0.22.7 installé par `uv sync --locked`.
- README, PR et textes publics en anglais ; commits en français, format conventionnel.
- Jamais de données réelles dans le dépôt : la démo vient de `tests/make_demo_profile.py` (noms et prompts inventés).
  Les profils Hermes de Théo se lisent par copie temporaire, supprimée après l'essai (essai du 5/11 : copie du serveur
  Hostinger arrêtée au 28/10 ; l'état courant des profils est sur l'A1, `~hermes/.hermes`, après le ménage du 4/11).
- `platforms:` du catalogue = ce qui est réellement testé : l'entrée dit `[linux, windows]` ; macOS ne s'y ajoute qu'avec
  une PR de catalogue (acte de Théo) et seulement si le job `hermes macos-latest` de la CI est vert.

## Pièges
- Le dossier du dépôt n'est pas importable (tiret) : les tests chargent le paquet sous `cron_consolidator`.
- Les grappes de « même minute » écartent les tâches à plus de 6 déclenchements par jour (`*/30` etc.) : sans cela
  un poller relie toutes les tâches en un seul groupe (constaté sur le profil réel).
- Sur le profil réel de Théo : 42 tâches actives, 30 sont des scripts (`no_agent`), un seul vrai candidat à la fusion.
  Ne pas promettre d'économie en tokens sans `usage_audit.jsonl` (il s'arrête au 28/10 sur ce serveur).
- `hermes plugins validate` saute `register_cli_command` (« skipped in the host ») : seul `tests/e2e_hermes.py` prouve que
  `hermes cron-consolidator report` existe dans le vrai analyseur de la CLI. Un tag de Hermes cloné sous un chemin Windows
  profond échoue à l'extraction (« retry with git restore ») : cloner sous un chemin court.
