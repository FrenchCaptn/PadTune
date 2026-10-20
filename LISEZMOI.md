# PadTune

🇬🇧 [English version](README.md)

<img src="assets/padtune_128.png" width="96" alt="Logo PadTune">

Réglage de la NYXI Flexi depuis Windows, sans téléphone :

- **Joysticks :** zone morte centrale, bord extérieur, courbe de sensibilité, inversion des axes, échange des sticks.
- **Gâchettes :** zone morte de début de course, fin de course, courbe, échange des gâchettes.
- **Boutons :** remappage de n'importe quel bouton vers un autre, ou désactivation.
- **Macros :** jusqu'à 8 macros, à éditer étape par étape ou à enregistrer directement depuis la manette, avec option de boucle.
- **Lumières :** couleur, mode fixe ou respiration, luminosité et vitesse.
- **Vibrations et veille :** intensité de chaque moteur et délai d'extinction automatique.

L'interface existe en **français, anglais, espagnol, allemand, italien et portugais** (menu 🌐 Langue).

L'appli utilise le même protocole Bluetooth que KeyLinker. Les réglages sont enregistrés **dans la manette**, donc ils restent valables en filaire, avec le dongle, sur Switch, etc.

## Installation

### Le plus simple : PadTune.exe

Télécharge **PadTune.exe** et double-clique dessus. Il n'y a rien d'autre à installer : Python et tout le reste sont inclus.

- **Windows SmartScreen :** l'exe n'est pas signé numériquement (un certificat coûte cher pour un projet gratuit), donc Windows peut afficher « Windows a protégé votre ordinateur ». Clique sur **Informations complémentaires**, puis **Exécuter quand même**.
- **Antivirus :** certains antivirus signalent à tort les applis construites avec PyInstaller. Le code source est disponible, et tu peux construire l'exe toi-même (voir plus bas).
- **Mode démo :** `PadTune.exe --demo` ouvre l'interface avec une manette simulée.

### Depuis le code source

Les noms de fichiers sont en anglais pour servir à tout le monde. Les messages des scripts `.bat` s'affichent en français si Windows est en français.

1. Installe **Python 3.14** (pas 3.15, pas encore compatible) depuis python.org : « Windows installer (64-bit) », en cochant « Add python.exe to PATH ».
2. Double-clique sur **Launch.bat**. La première fois, il installe ce qu'il faut (environ 1 minute).

`Demo.bat` ouvre l'interface avec une manette simulée, pour la découvrir sans risque.

Pour lancer PadTune comme une application normale, double-clique sur **Create shortcut.bat** après le premier lancement. Il ajoute un raccourci PadTune, avec son icône, sur le Bureau et dans le menu Démarrer.

### Construire PadTune.exe

- **Sur ton PC :** double-clique sur **Build exe.bat**. Il installe PyInstaller, construit `dist\PadTune.exe`, vérifie qu'il démarre correctement, puis ouvre le dossier.
- **Automatiquement sur GitHub :** le fichier `.github/workflows/build-windows.yml` construit et vérifie l'exe sous Windows. Il se lance chaque fois que tu publies une version (tag `v1.0.0`, `v1.1.0`…) et joint `PadTune.exe` à la page de la release. Tu peux aussi le lancer à la main depuis l'onglet **Actions**.

Si tu utilisais la version précédente (Flexi Config), tes sauvegardes et ton favori sont repris automatiquement : l'ancien dossier `%APPDATA%\FlexiConfig` est renommé en `%APPDATA%\PadTune`, et l'ancien fichier `parametres.json` est converti en `settings.json`.

## Utilisation

1. **Ferme KeyLinker** (et coupe le Bluetooth du téléphone) : la manette n'accepte qu'une connexion de configuration à la fois.
2. **Allume la manette**, dans le mode que tu utilises d'habitude (dongle, Bluetooth…). Pas besoin de changer de mode ni de l'associer à Windows : PadTune la trouve tout seul, du moment que le Bluetooth du PC est activé.
3. La recherche se lance toute seule à l'ouverture de l'appli (bouton **Rechercher** pour la relancer). Choisis l'appareil marqué ★, puis **Connecter**.
4. L'appli lit les réglages actuels et en fait une **sauvegarde automatique** dans `%APPDATA%\PadTune\`.
5. Modifie les réglages, puis clique sur **Appliquer à la manette**. L'appli relit la manette pour vérifier que les valeurs ont bien été enregistrées.

**Affichage en direct** (activé par défaut) : bouge les sticks pour voir deux points dans le cercle.

- Le **point blanc** est la position réelle du stick.
- Le **point rouge** est ce que le jeu recevra avec les réglages affichés, même avant d'avoir cliqué sur Appliquer.

Sous le cercle, `brut X % → sortie Y %` indique de combien le stick est poussé. C'est le moyen le plus simple de régler la zone morte au plus juste : pousse très légèrement le stick et vérifie que la sortie bouge.

**Favori et connexion automatique :** une fois connecté, clique sur **☆ Favori**. Le bouton devient « ★ Favori » et l'appareil est mémorisé dans `%APPDATA%\PadTune\settings.json`. Ensuite :

- à chaque démarrage, l'appli recherche les manettes et se connecte toute seule au favori dès qu'il est détecté ;
- si le favori n'est pas encore allumé, elle relance discrètement une recherche toutes les 8 secondes ;
- si la connexion est perdue, elle se reconnecte automatiquement ;
- si tu cliques sur **Déconnecter**, elle ne se reconnecte plus jusqu'à ta prochaine recherche manuelle.

Clique à nouveau sur ★ Favori pour retirer la manette des favoris.

Pour revenir aux réglages d'origine, utilise **Importer…** avec le fichier de sauvegarde, puis **Appliquer**.

## Les réglages

### Joysticks

| Réglage | Signification |
|---|---|
| Zone morte centrale | Pourcentage de course ignoré au centre (0 = aucune) |
| Bord extérieur | Position à partir de laquelle le stick est considéré à fond (100 = course complète) |
| Courbe | 2 points de contrôle sur une grille 0–255, mêmes préréglages que KeyLinker. Les points se **déplacent à la souris** directement sur la courbe (la courbe devient alors « Personnalisée »). |
| Inverser X / Y | Inversion des axes |
| Échanger les sticks | Inverse les sticks gauche et droit |

La croix en pointillés marque le centre du stick.

### Gâchettes

Mêmes principes que pour les sticks. La **zone morte** est la partie du début de course ignorée, et la **fin de course** est le point à partir duquel la gâchette est considérée à fond. La barre affiche la position réelle (trait blanc) et la valeur envoyée au jeu (barre rouge).

### Boutons

Pour chaque bouton physique, choisis ce qu'il envoie : un autre bouton ou « — désactivé — ». Les boutons remappés apparaissent en gras. Quand l'affichage en direct est actif, la ligne du bouton pressé s'allume en jaune. « Tout remettre par défaut » annule tous les remappages.

La liste des boutons proposés est celle que la manette déclare elle-même.

### Macros

Une macro est une suite d'**étapes**. Chaque étape maintient des boutons enfoncés (et éventuellement une direction de croix ou de stick) pendant une durée en millisecondes. Par exemple, « A pendant 50 ms, puis rien pendant 30 ms, puis B pendant 50 ms » donne un enchaînement A puis B.

- **Choisir l'emplacement :** la liste « Macro » propose ceux que la manette accepte (jusqu'à 8). Les macros se déclenchent avec les boutons de macro de la manette, en général les boutons arrière, qui s'assignent sur la manette elle-même.
- **Éditer :** « + Étape » ajoute une étape. Le bouton « Boutons » de chaque ligne ouvre la liste des boutons à cocher. ↑ et ↓ déplacent l'étape sélectionnée.
- **Enregistrer :** « ● Enregistrer depuis la manette » capture tes appuis avec leur durée réelle, puis « ■ Arrêter » les transforme en étapes. Coche « Inclure les sticks » pour enregistrer aussi les directions des sticks.
- **Boucle :** la macro se répète, avec la pause indiquée entre deux répétitions.

### Lumières

Couleur (clic sur la pastille pour ouvrir le sélecteur, ou valeurs R/V/B), mode **Fixe** ou **Respiration**, luminosité, et vitesse de la respiration.

### Vibrations et veille

Intensité de 0 à 100 % pour chaque moteur (0 % coupe la vibration). La mise en veille règle le délai d'inactivité avant l'extinction de la manette, ou « Jamais ».

**Appliquer** n'envoie que ce qui a changé, et l'affiche sur le bouton (par exemple « 2 modif. »). Si un onglet est grisé, c'est que la manette n'a pas répondu pour ce type de réglage.

## Langue

Le menu **🌐 Langue**, en haut de la fenêtre, propose Français, English, Español, Deutsch, Italiano et Português. Le choix est mémorisé, et l'appli propose de redémarrer pour l'appliquer. Au tout premier lancement, PadTune prend la langue de Windows si elle est disponible, sinon l'anglais.

Pour corriger ou ajouter une traduction, modifie `translations.py` : chaque texte français y est associé à sa traduction. Les repères entre accolades, comme `{name}`, doivent rester identiques.

## Compatibilité avec d'autres manettes

PadTune ne vérifie pas le modèle de la manette. Il cherche le **service Bluetooth de KeyLinker** (l'appareil marqué ★), puis demande à la manette ce qu'elle sait faire : liste de ses boutons, boutons utilisables en macro, emplacements de macro, zones lumineuses. Les onglets qu'elle ne gère pas restent grisés.

Il devrait donc fonctionner avec **les autres manettes compatibles KeyLinker**, c'est-à-dire celles qui se configurent avec l'appli KeyLinker. Seule la NYXI Flexi a été testée. Les manettes d'autres marques qui ont leur propre appli (Xbox, DualSense, 8BitDo, GameSir…) utilisent des protocoles différents et ne fonctionneront pas.

## Si ça ne marche pas

- **La manette n'apparaît pas :** vérifie qu'elle est allumée, que le Bluetooth du PC est activé et que KeyLinker est fermé sur le téléphone. Si elle est déjà associée à Windows comme manette, il peut falloir la retirer de Paramètres → Bluetooth.
- **Elle apparaît sans ★ :** connecte-toi quand même. Le service n'est pas toujours annoncé avant la connexion.
- **« Pas de réponse de la manette » :** déconnecte, éteins puis rallume la manette, et réessaie.
- Le journal en bas de la fenêtre affiche les trames échangées. Copie-le si tu demandes de l'aide.

## Comment ça marche

`flexi_protocol.py` contient le protocole reconstitué à partir de l'appli KeyLinker (`com.pulsenet.inputset`) :

- **Canal :** service BLE `d7f010e0-660d-46e9-96c3-19c4148bdab5`. L'écriture se fait sur `…e1`, les notifications arrivent sur `…e2`.
- **Format des trames :** `[commande, longueur, n° de série, aléatoire, données…, CRC8]`, puis brouillage par XOR avec des tables fixes.
- **Affichage en direct :** l'appli envoie la commande 29 (mode 7) toutes les 750 ms. En retour, la manette diffuse des trames de commande 31 avec la position brute de chaque stick (0–255).
- **Blocs de réglages :** chaque bloc se lit et s'écrit avec une paire de commandes. La manette répond par un accusé (commande 25) qui reprend le n° de série de la requête.
  - Joysticks : lecture 177, écriture 49 (15 octets).
  - Gâchettes : lecture 178, écriture 50 (15 octets, échelle 0–200).
  - Vibrations et veille : lecture 179, écriture 51 (9 octets : 4 moteurs, puis le délai en unités de 5 ms).
  - Boutons : la liste des boutons se lit avec la commande 176 `[page, 3]`, en liste compressée. Le remappage se lit avec la commande 182 `[page]` et s'écrit avec la commande 54, par tranches de 15 valeurs. Chaque valeur vaut 0 (inchangé), le code du bouton lui-même (désactivé) ou le code du bouton cible.
  - Lumières : lecture 183 `[page]`, écriture 55 par tranches. 6 octets par zone : R, V, B, vitesse (bits bas), mode et vitesse (bits hauts), luminosité.
  - Macros : la liste des boutons utilisables se lit avec la commande 176 `[page, 5]`, puis chaque emplacement avec la commande 181 `[page, emplacement]`. L'écriture se fait avec la commande 53, l'emplacement étant codé dans l'octet 1. L'en-tête contient la taille, l'intervalle et la boucle, puis viennent 5 octets par étape : un masque de 24 bits (1 bit par bouton et par direction de croix, 4 bits par stick) et la durée en unités de 5 ms. La commande 176 `[0, 1]` indique le format d'en-tête (v1 ou v2).
- **Affichage des boutons en direct :** les trames de commande 31 contiennent aussi des entrées `[état, code]`. Sur l'onglet Boutons, le signal de maintien passe en mode 8, comme dans KeyLinker.

Les tests (`tests/`) vérifient que l'encodage donne exactement les mêmes octets que le code Java d'origine.

