"""Point d'entrée de l'application de bureau (c'est ce fichier que PyInstaller transforme en .exe / .app).
Développement : python lanceur.py"""
from agent_avocat.app import reglages

reglages.preparer_dossier()          # AVANT tout import de agent_avocat.config

from agent_avocat.app.fenetre import main  # noqa: E402

if __name__ == "__main__":
    main()
