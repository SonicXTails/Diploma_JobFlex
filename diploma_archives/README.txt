Diploma delivery archives (JobFlex)
===================================

Run from repository root:

  python diploma_archives/build_diploma_zips.py

Output in this folder:

1) JobFlex_operational_package.zip
   Plus a copy with a Russian filename (Explorer shows it correctly).
   Contents: requirements, .env.example, manage.py, run_all.py, README, operator guide, tools scripts.

2) JobFlex_program_sources.zip
   Plus a copy with a Russian filename.
   Full project tree without: .git, .venv, __pycache__, .env, db.sqlite3, media, staticfiles, backups, logs, diploma_archives.

If Windows console mangles Cyrillic file names, use the JobFlex_*.zip files — they are identical to the Russian-named copies.
