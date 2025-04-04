# AutoEditor Video - Cut Only

Ce projet est une interface graphique pour l'édition vidéo automatique, utilisant FFmpeg pour détecter les silences et extraire les segments actifs d'une vidéo.

## Fonctionnalités

- Détection des silences dans une vidéo
- Extraction des segments actifs
- Réencodage des segments extraits
- Concatenation des segments extraits
- Interface graphique simple avec Tkinter

## Prérequis

- Python 3.x
- FFmpeg installé et accessible via la ligne de commande

## Installation

1. Clonez ce dépôt :
    ```bash
    git clone https://github.com/votre-utilisateur/autoeditor-video-cut-only.git
    cd autoeditor-video-cut-only
    ```

2. Installez les dépendances requises :
    ```bash
    pip install -r requirements.txt
    ```

## Utilisation

1. Lancez l'interface graphique :
    ```bash
    python main.py
    ```

2. Sélectionnez le fichier vidéo à traiter.
3. Choisissez le fichier de sortie.
4. Cliquez sur "Démarrer" pour lancer le traitement.
