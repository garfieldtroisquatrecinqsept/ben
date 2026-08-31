# Bot Discord « bruits de Ben »

Un bot qui rejoint ton salon vocal et balance les voix de Talking Ben, tout seul.
Ses commandes ne laissent aucune trace dans le salon texte.

## Contenu

| Fichier | Rôle |
|---|---|
| `All talking Ben voice lines (free to use).mp3` | le MP3 source |
| `split_ben.py` | découpe le MP3 en clips séparés (détection de silence via ffmpeg) |
| `sounds/` | les clips — **le nom du fichier = le nom du son dans Discord** |
| `bot.py` | le bot |
| `model/` | modèle de reconnaissance vocale (optionnel, voir *Écoute*) |
| `diag_vocal.py` | diagnostic de la réception vocale, si l'écoute ne marche plus |
| `run_bot.bat` | double-clic pour lancer sous Windows |
| `main.py` | point d'entrée des hébergeurs type Pterodactyl (diagnostic + modèle) |
| `start.sh` | même rôle en bash, pour un VPS ou un hôte qui laisse choisir |

## Lancer

```bash
cd "C:\Users\Administrateur\Desktop\APP_REPO\BEN" && .venv\Scripts\python.exe -X utf8 bot.py
```

Ou double-clic sur `run_bot.bat`.

## Comment ça marche

Tu fais `/join` (ou `/ben`) une fois, et à partir de là il se débrouille :

- **Ambiance** — dès qu'il est connecté, il lâche un bruit au hasard toutes les
  **5 à 10 minutes**. C'est le comportement par défaut, rien à activer.
- **Écoute** — si quelqu'un dit « Ben » dans le vocal, il répond par un bruit.
- **Texte** — si « ben » apparaît dans un message écrit, il répond `no` ou `yes`
  à ce message, sans avoir besoin d'être mentionné (demande `MESSAGES=true`).
- Il quitte tout seul le vocal quand il n'y a plus personne.

Aucune **commande** ne poste de message visible : leurs réponses sont éphémères
(toi seul les vois) et disparaissent aussitôt. Seule la réaction au mot « ben »
écrit produit un message que tout le monde voit.

## Commandes

| Commande | Effet |
|---|---|
| `/join` | Ben rejoint ton salon vocal et lance l'ambiance |
| `/ben` | balance un bruit tout de suite (au hasard, ou celui que tu choisis) |
| `/intervalle mini maxi` | change l'attente de l'ambiance, en minutes |
| `/sons` | liste les sons |
| `/stop` | coupe l'ambiance et le son en cours |
| `/leave` | quitte le vocal |
| `/reload` | recharge `sounds/` sans redémarrer |

`/intervalle 2 4` → un bruit toutes les 2 à 4 minutes, jusqu'au redémarrage.
Pour changer la valeur **par défaut**, édite `INTERVALLE_MIN` / `INTERVALLE_MAX`
dans `.env`.

## Réglages (`.env`)

| Clé | Défaut | Effet |
|---|---|---|
| `DISCORD_TOKEN` | — | le token du bot |
| `GUILD_ID` | — | ton serveur, pour la synchro immédiate des commandes |
| `INTERVALLE_MIN` / `INTERVALLE_MAX` | `5` / `10` | ambiance, en minutes |
| `ECOUTE` | `true` | reconnaissance vocale activée ou non |
| `MOT_CLE` | `ben` | le mot qui le réveille |
| `DELAI_ECOUTE` | `1.5` | temps mort en secondes après une réponse |
| `SEUIL_ECOUTE` | `0.9` | confiance minimum (0 à 1) pour déclencher |
| `LEURRES` | voir ci-dessous | mots proches ajoutés au vocabulaire |
| `MESSAGES` | `false` | lecture des salons texte : reponses ecrites + commandes `!ben` |
| `REPONSES_TEXTE` | `no yes` | reponses tirees au sort dans les salons texte |

## Écoute (reconnaissance vocale)

Elle tourne en local, hors ligne, avec [Vosk](https://alphacephei.com/vosk/)
(modèle français `vosk-model-small-fr-0.22`, déjà installé dans `model/`). Le flux
vocal Discord (48 kHz stéréo) est converti en 16 kHz mono puis transcrit. Rien
n'est enregistré ni envoyé ailleurs : l'audio est traité au fil de l'eau puis jeté.

**Il ne réagit qu'à « ben ».** C'est le point délicat : avec un vocabulaire réduit
au seul mot-clé, Vosk rabat n'importe quel mot en B dessus. La parade est
d'ajouter des **leurres** — des mots proches qui lui donnent un meilleur candidat
que « ben » — plus un seuil de confiance. Mesuré sur 5 « ben » et ~43 s de français
sans « ben » :

| réglage | détectés | faux positifs |
|---|---|---|
| mot-clé seul | 5/5 | 4 |
| **+ 11 leurres, seuil 0.9** | **5/5** | **0** |
| vocabulaire complet | 3/5 | 0 |

Attention si tu touches à `LEURRES` : des mots trop proches (`benne`, `bain`)
volent les vraies détections et font tomber la reconnaissance à zéro.

### Pourquoi il fallait dire « ben » dix fois

Discord n'envoie des paquets audio **que pendant qu'on parle** : dans les blancs,
le flux s'arrête net. Vosk, lui, a besoin d'entendre du silence pour décider
qu'une phrase est finie et rendre son résultat. Sans silence, il garde le mot en
attente et ne le rend qu'au moment où on reparle — d'où une réaction pour
plusieurs « ben ».

`SilenceGeneratorSink` (fourni par `discord-ext-voice-recv`) fabrique du silence
pendant les blancs et règle le problème. Mesuré sur les mêmes 5 « ben », en
reproduisant le comportement réel de Discord :

| ce que voit Vosk | détections |
|---|---|
| paquets Discord bruts, aucun silence | 2/5 |
| silence seulement à la fin | 2/5 |
| **silence pendant chaque blanc** | **5/5** |

Deux réglages allaient dans le même sens et ont été corrigés :

- le bot coupait son écoute pendant qu'il parlait. Sauter des trames au milieu
  d'un mot casse le flux de Vosk. Il écoute désormais en continu — Discord ne lui
  renvoie pas sa propre voix, il ne risque pas de s'entendre.
- `DELAI_ECOUTE` était à 5 s : quinze « ben » d'affilée ne pouvaient donner que
  trois réactions au mieux. Il est passé à 1.5 s.

Sans le dossier `model/`, le bot démarre quand même et affiche
`Ecoute desactivee - modele absent` ; tout le reste fonctionne.

### Vosk n'est pas thread-safe, et deux threads l'appellent

Symptôme : le bot répond correctement, puis le process est tué net.

```
WARNING (VoskAPI:BestPathEnd()) No final token found.
ASSERTION_FAILED (VoskAPI:TraceBackBestPath()) Assertion failed
```

Ce n'est pas une exception Python — c'est une assertion C++, `try/except` ne peut
rien intercepter.

La cause est une course entre deux threads. `SilenceGeneratorSink` n'est pas un
simple filtre : il lance **son propre thread** (`SilenceGenerator(threading.Thread)`)
qui appelle `write()` pour injecter du silence, pendant que le thread de routage
des paquets appelle `write()` avec l'audio réel. Les deux touchaient le même
`KaldiRecognizer`, qui ne supporte pas ça : le treillis de décodage se corrompt,
`Result()` ne trouve plus de token final, et Vosk abandonne le process.

Un `threading.Lock` autour de l'analyse règle le problème. Vérifié en rejouant la
course dans un sous-processus, huit passages, deux threads :

| verrou | résultat |
|---|---|
| désactivé | process tué, code de sortie 3 |
| actif | survit, 0 exception |

Une explication antérieure accusait `KaldiRecognizer.Reset()`. Le retirer était
juste — `AcceptWaveform()` clôt déjà l'énoncé, `Reset()` était inutile — mais ce
n'était pas la cause : le crash revient sans lui. Le vrai coupable est la course.

### Le rustine DAVE (chiffrement de bout en bout)

Discord chiffre l'audio de bout en bout : c'est le protocole **DAVE**, géré côté
`discord.py` par la librairie `davey`. `discord-ext-voice-recv` (0.5.2a179, la
dernière version) **ignore complètement cette couche** : il déchiffre le
transport, puis passe à Opus des octets encore chiffrés. D'où :

```
discord.opus.OpusError: corrupted stream
```

et la mort du thread de routage — le bot reste connecté mais sourd.

Se déclarer incompatible avec DAVE (`max_dave_protocol_version = 0`) **ne marche
pas** : le serveur ferme aussitôt la connexion avec le code `4017`, en boucle.

`patch_dave_receive()` dans `bot.py` intercale donc le déchiffrement DAVE avant le
décodage Opus, en réutilisant la session que `discord.py` maintient déjà. Le
chiffrement de bout en bout reste actif.

Deux garde-fous, appris à la dure — sans eux **un seul** paquet abîmé tue le
thread de routage et le bot reste connecté mais définitivement sourd :

- dès que le chiffrement de bout en bout est négocié, tout paquet qu'on n'a pas
  pu déchiffrer est jeté. Il ne doit **jamais** partir vers Opus. Ça arrive quand
  Discord n'a pas encore dit à quel utilisateur appartient un flux (`unknown
  ssrc`), quand la session n'est pas prête, ou pendant un changement d'époque.
- le décodage Opus lui-même est enveloppé : une `OpusError` fait sauter le
  paquet, pas le thread.

C'est du monkeypatch sur `PacketDecoder._decode_packet` : à surveiller lors d'une
mise à jour de `discord-ext-voice-recv`, qui finira par gérer DAVE nativement.
En cas de casse, `ECOUTE=false` désactive toute la réception et le bot retombe sur
un client vocal standard, ambiance et commandes intactes.

## Héberger sur bot-hosting.net (ou tout panel Pterodactyl)

La commande de démarrage du panel est figée :

```
pip install -r requirements.txt && exec python3 -u ${STARTUP_FILE}
```

Elle n'exécute qu'un fichier **Python**, donc `start.sh` y est inutilisable.
`main.py` est le point d'entrée pour ces hébergeurs : il fait le diagnostic,
télécharge le modèle Vosk si besoin, puis lance le bot. Comme `main.py` est aussi
la valeur par défaut de `STARTUP_FILE`, il n'y a rien à changer dans le panel.

| Champ | Valeur |
|---|---|
| Git Repo Address | `https://github.com/garfieldtroisquatrecinqsept/ben.git` |
| Branch | `main` |
| STARTUP_FILE | `main.py` (valeur par défaut, rien à toucher) |
| Variables | `DISCORD_TOKEN`, `GUILD_ID`, `MESSAGES`… |

Pas de fichier `.env` à créer : les variables du panel sont lues directement par
`os.getenv`. Le `.env` local reste prioritaire s'il existe, mais il n'est pas dans
le dépôt — et ne doit jamais y être.

`start.sh` reste dans le dépôt pour les hébergeurs qui laissent choisir la
commande de démarrage, et pour un VPS.

**Vérifié sur bot-hosting.net (image Python 3.14, Linux x86_64)** : toutes les
dépendances s'installent, roues Linux comprises — `vosk`, `davey` (`cp314`),
`PyNaCl`, et `audioop-lts` qui remplace le module `audioop` retiré de Python 3.13.

**Ce qui peut encore manquer dans l'image**, et que le diagnostic affiche :

- **ffmpeg** — sans lui, aucun son n'est joué. Aucun contournement côté code, il
  faut une autre image.
- **libopus** — `discord.py` ne la fournit que pour Windows ; sous Linux elle doit
  venir du système. Absente, le bot rejoint le vocal mais n'encode rien.

**Ressources.** Le modèle occupe 66 Mo sur le disque et environ 200 Mo de RAM une
fois chargé, et la reconnaissance décode 50 trames par seconde et par personne qui
parle. C'est la partie coûteuse. Si le conteneur est trop juste, mets
`ECOUTE=false` : le téléchargement est sauté, et le bot garde l'ambiance, les
commandes et les réponses écrites pour presque rien.

## Redécouper le MP3

`split_ben.py` repère les passages sonores, jette les blancs, normalise le volume
et écrit `sounds/ben_01.mp3`, `ben_02.mp3`, …

```bash
python split_ben.py --dry-run
```

- `--gap 0.3` : sépare davantage — `--gap 1.0` : regroupe
- `--noise -50` : capte les sons plus faibles
- `--min-dur 0.3` : ignore les clips très courts

Relancer le script écrase les `ben_XX.mp3`, mais **pas** les fichiers renommés.

## Invitation

Application `Ben#7062`, ID `1543922898903896104` :

https://discord.com/oauth2/authorize?client_id=1543922898903896104&permissions=3214336&scope=bot+applications.commands

Le scope `applications.commands` est indispensable, sinon les slash commands ne
peuvent pas être publiées (`403 Missing Access`).

### Réponses dans les salons texte

Lire le contenu des messages demande l'intent privilégié **Message Content**,
à cocher dans le portail développeur (onglet *Bot*), puis `MESSAGES=true` dans
`.env`. Les deux vont ensemble :

- intent coché mais `MESSAGES=false` → le bot ignore les messages
- `MESSAGES=true` mais intent décoché → **Discord refuse la connexion** et le bot
  boucle sur « session has been invalidated »

Le mot est cherché avec des frontières de mot : `ben`, `Ben tu fais quoi`, `BEN!`
déclenchent ; `bien`, `benjamin`, `superben` non. Le bot répond en citant le
message, sans mentionner son auteur.

Le lien d'invitation ci-dessus inclut *Lire l'historique des messages*, nécessaire
pour répondre à un message. Si le bot est déjà invité, ajoute cette permission à
son rôle ou réinvite-le avec ce lien.
