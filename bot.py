import asyncio
import audioop
import json
import logging
import os
import random
import re
import time
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
SOUNDS_DIR = ROOT / "sounds"
MODEL_DIR = ROOT / "model"

load_dotenv(ROOT / ".env")
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")
MESSAGES = os.getenv("MESSAGES", os.getenv("MESSAGE_COMMANDS", "")).lower() in (
    "1",
    "true",
    "yes",
    "oui",
)
REPONSES_TEXTE = os.getenv("REPONSES_TEXTE", "no yes").split()

INTERVALLE_MIN = float(os.getenv("INTERVALLE_MIN", "5"))
INTERVALLE_MAX = float(os.getenv("INTERVALLE_MAX", "10"))
MOT_CLE = os.getenv("MOT_CLE", "ben").lower()
ECOUTE = os.getenv("ECOUTE", "true").lower() in ("1", "true", "yes", "oui")
DELAI_ECOUTE = float(os.getenv("DELAI_ECOUTE", "1.5"))
SEUIL_ECOUTE = float(os.getenv("SEUIL_ECOUTE", "0.9"))
LEURRES = os.getenv(
    "LEURRES", "bonjour bonsoir bon bonne bien beau banc blanc banane bonbon"
).lower().split()

GRAMMAIRE = [MOT_CLE] + [m for m in LEURRES if m != MOT_CLE] + ["[unk]"]
MOT_ECRIT = re.compile(r"\b" + re.escape(MOT_CLE) + r"\b", re.IGNORECASE)

FFMPEG_OPTS = {
    "before_options": "-nostdin",
    "options": "-vn -loglevel error",
}

for _bavard in ("discord.ext.voice_recv.reader", "discord.ext.voice_recv.gateway"):
    logging.getLogger(_bavard).setLevel(logging.WARNING)

intents = discord.Intents.default()
intents.voice_states = True
intents.message_content = MESSAGES

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

sounds: dict[str, Path] = {}
ambiance_tasks: dict[int, asyncio.Task] = {}
intervalles: dict[int, tuple[float, float]] = {}

_vosk_model = None
_vosk_erreur: str | None = None


def load_sounds() -> int:
    sounds.clear()
    for path in sorted(SOUNDS_DIR.glob("*.mp3")):
        sounds[path.stem.lower()] = path
    return len(sounds)


def get_vosk_model():
    global _vosk_model, _vosk_erreur
    if _vosk_model is not None or _vosk_erreur is not None:
        return _vosk_model
    if not MODEL_DIR.is_dir():
        _vosk_erreur = f"modele absent : {MODEL_DIR} (voir DOCUMENTATION.md)"
        print(f"Ecoute desactivee - {_vosk_erreur}")
        return None
    try:
        from vosk import Model, SetLogLevel

        SetLogLevel(-1)
        _vosk_model = Model(str(MODEL_DIR))
        print("Modele de reconnaissance vocale charge")
    except Exception as exc:
        _vosk_erreur = f"{type(exc).__name__}: {exc}"
        print(f"Ecoute desactivee - {_vosk_erreur}")
    return _vosk_model


async def play_sound(vc: discord.VoiceClient, path: Path):
    if vc.is_playing():
        vc.stop()
    done = asyncio.Event()
    loop = asyncio.get_running_loop()

    def after(error):
        if error:
            print(f"Erreur de lecture : {error}")
        loop.call_soon_threadsafe(done.set)

    source = discord.FFmpegPCMAudio(str(path), **FFMPEG_OPTS)
    vc.play(discord.PCMVolumeTransformer(source, volume=0.8), after=after)
    await done.wait()


async def play_random(vc: discord.VoiceClient, origine: str = "?"):
    if sounds and vc.is_connected():
        nom, chemin = random.choice(list(sounds.items()))
        print(f"[{origine}] {nom}")
        await play_sound(vc, chemin)


def start_ambiance(guild_id: int, vc: discord.VoiceClient):
    stop_ambiance(guild_id)

    async def boucle():
        try:
            while vc.is_connected():
                low, high = intervalles.get(guild_id, (INTERVALLE_MIN, INTERVALLE_MAX))
                await asyncio.sleep(random.uniform(low * 60, high * 60))
                await play_random(vc, "ambiance")
        except asyncio.CancelledError:
            pass

    ambiance_tasks[guild_id] = asyncio.create_task(boucle())


def stop_ambiance(guild_id: int):
    task = ambiance_tasks.pop(guild_id, None)
    if task is not None:
        task.cancel()


try:
    from discord.ext import voice_recv as _voice_recv

    _SinkBase = _voice_recv.AudioSink
except ImportError:
    _voice_recv = None
    _SinkBase = object


class WakeWordSink(_SinkBase):

    def __init__(self, vc: discord.VoiceClient, model, loop: asyncio.AbstractEventLoop):
        if _SinkBase is not object:
            super().__init__()
        self.vc = vc
        self.model = model
        self.loop = loop
        self.recognizers: dict[int, object] = {}
        self.resample_states: dict[int, object] = {}
        self.dernier_declenchement = 0.0

    def wants_opus(self) -> bool:
        return False

    def write(self, user, data) -> None:
        if user is None or user.bot or not sounds or not data.pcm:
            return
        mono = audioop.tomono(data.pcm, 2, 0.5, 0.5)
        converted, self.resample_states[user.id] = audioop.ratecv(
            mono, 2, 1, 48000, 16000, self.resample_states.get(user.id)
        )

        rec = self.recognizers.get(user.id)
        if rec is None:
            from vosk import KaldiRecognizer

            rec = KaldiRecognizer(self.model, 16000, json.dumps(GRAMMAIRE))
            rec.SetWords(True)
            self.recognizers[user.id] = rec

        if not rec.AcceptWaveform(converted):
            return
        mots = json.loads(rec.Result()).get("result", [])
        if not any(w["word"] == MOT_CLE and w["conf"] >= SEUIL_ECOUTE for w in mots):
            return

        maintenant = time.monotonic()
        if maintenant - self.dernier_declenchement < DELAI_ECOUTE:
            return
        self.dernier_declenchement = maintenant
        nom = getattr(user, "display_name", user)
        print(f"[ecoute] '{MOT_CLE}' entendu ({nom})")
        asyncio.run_coroutine_threadsafe(play_random(self.vc, "ecoute"), self.loop)

    def cleanup(self) -> None:
        self.recognizers.clear()
        self.resample_states.clear()


def start_ecoute(vc):
    if not ECOUTE or not hasattr(vc, "listen"):
        return False
    model = get_vosk_model()
    if model is None:
        return False
    try:
        from discord.ext import voice_recv

        sink = WakeWordSink(vc, model, asyncio.get_running_loop())
        vc.listen(voice_recv.SilenceGeneratorSink(sink))
        return True
    except Exception as exc:
        print(f"Ecoute impossible : {type(exc).__name__}: {exc}")
        return False


_dave_patch = False
_dave_erreurs = 0


def patch_dave_receive() -> bool:
    global _dave_patch
    if _dave_patch:
        return True

    import davey
    from discord.ext.voice_recv import opus as voice_recv_opus

    decode_original = voice_recv_opus.PacketDecoder._decode_packet

    def decode_dechiffre(self, packet):
        global _dave_erreurs
        connexion = self.sink.voice_client._connection
        chiffre = getattr(connexion, "dave_protocol_version", 0) > 0

        if packet and chiffre:
            session = getattr(connexion, "dave_session", None)
            user_id = self.sink.voice_client._get_id_from_ssrc(self.ssrc)
            clair = None
            if session is not None and session.ready and user_id is not None:
                try:
                    clair = session.decrypt(user_id, davey.MediaType.audio, packet.decrypted_data)
                except Exception as exc:
                    _dave_erreurs += 1
                    if _dave_erreurs in (1, 100, 1000):
                        print(f"Dechiffrement DAVE en echec ({_dave_erreurs}e) : {exc}")
            if not clair:
                _dave_erreurs += 1
                if _dave_erreurs in (1, 100, 1000):
                    raison = (
                        "expediteur inconnu" if user_id is None
                        else "session pas prete" if session is None or not session.ready
                        else "dechiffrement refuse"
                    )
                    print(f"Paquet audio ignore ({raison}, {_dave_erreurs}e)")
                return packet, b""
            packet.decrypted_data = clair

        try:
            return decode_original(self, packet)
        except discord.opus.OpusError as exc:
            _dave_erreurs += 1
            if _dave_erreurs in (1, 100, 1000):
                print(f"Paquet audio illisible, ignore ({_dave_erreurs}e) : {exc}")
            return packet, b""

    voice_recv_opus.PacketDecoder._decode_packet = decode_dechiffre
    _dave_patch = True
    return True


def voice_client_class():
    if ECOUTE:
        try:
            from discord.ext import voice_recv

            patch_dave_receive()
            return voice_recv.VoiceRecvClient
        except Exception as exc:
            print(f"Ecoute indisponible ({type(exc).__name__}: {exc}), vocal standard")
    return discord.VoiceClient


async def ensure_voice(interaction: discord.Interaction) -> discord.VoiceClient | None:
    user = interaction.user
    if not isinstance(user, discord.Member) or user.voice is None or user.voice.channel is None:
        await reply(interaction, "Faut etre dans un salon vocal d'abord.")
        return None

    channel = user.voice.channel
    vc = interaction.guild.voice_client
    if vc is None:
        vc = await channel.connect(cls=voice_client_class())
        start_ambiance(interaction.guild.id, vc)
        start_ecoute(vc)
    elif vc.channel != channel:
        await vc.move_to(channel)
    return vc


async def reply(interaction: discord.Interaction, message: str):
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


async def silent_ack(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        await interaction.delete_original_response()
    except discord.HTTPException:
        pass


async def sound_autocomplete(interaction: discord.Interaction, current: str):
    current = current.lower()
    return [
        app_commands.Choice(name=name, value=name)
        for name in sounds
        if current in name
    ][:25]


@bot.event
async def on_ready():
    count = load_sounds()
    print(f"Connecte en tant que {bot.user} - {count} son(s) charge(s)")
    print(f"Ambiance : un bruit toutes les {INTERVALLE_MIN:g} a {INTERVALLE_MAX:g} min")
    if ECOUTE:
        get_vosk_model()
    try:
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
        else:
            await bot.tree.sync()
    except Exception as exc:
        print(f"Synchro des commandes impossible : {exc}")


@bot.tree.command(name="join", description="Ben rejoint ton salon vocal")
async def join(interaction: discord.Interaction):
    vc = await ensure_voice(interaction)
    if vc is not None:
        await silent_ack(interaction)


@bot.tree.command(name="ben", description="Balance un bruit de Ben")
@app_commands.describe(son="Un son precis (par defaut : au hasard)")
@app_commands.autocomplete(son=sound_autocomplete)
async def ben(interaction: discord.Interaction, son: str | None = None):
    if not sounds:
        await reply(interaction, "Aucun son dans sounds/.")
        return

    if son is None:
        name = random.choice(list(sounds))
    else:
        name = son.lower()
        if name not in sounds:
            await reply(interaction, f"Connais pas `{son}`. Voir /sons.")
            return

    vc = await ensure_voice(interaction)
    if vc is None:
        return
    await silent_ack(interaction)
    print(f"[commande] {name}")
    await play_sound(vc, sounds[name])


@bot.tree.command(name="sons", description="Liste les bruits disponibles")
async def liste(interaction: discord.Interaction):
    if not sounds:
        await reply(interaction, "Aucun son dans sounds/.")
        return
    await reply(interaction, "\n".join(f"- `{name}`" for name in sounds))


@bot.tree.command(name="intervalle", description="Regle l'attente entre deux bruits d'ambiance")
@app_commands.describe(mini="Minutes minimum", maxi="Minutes maximum")
async def intervalle(interaction: discord.Interaction, mini: float, maxi: float):
    if mini < 0.1 or maxi < mini:
        await reply(interaction, "Valeurs invalides (mini >= 0.1 et maxi >= mini).")
        return
    intervalles[interaction.guild.id] = (mini, maxi)
    await reply(interaction, f"Ambiance : un bruit toutes les {mini:g} a {maxi:g} min.")


@bot.tree.command(name="stop", description="Coupe l'ambiance et le son en cours")
async def stop(interaction: discord.Interaction):
    stop_ambiance(interaction.guild.id)
    vc = interaction.guild.voice_client
    if vc is not None and vc.is_playing():
        vc.stop()
    await silent_ack(interaction)


@bot.tree.command(name="leave", description="Ben quitte le vocal")
async def leave(interaction: discord.Interaction):
    stop_ambiance(interaction.guild.id)
    vc = interaction.guild.voice_client
    if vc is None:
        await reply(interaction, "Je suis dans aucun vocal.")
        return
    await vc.disconnect()
    await silent_ack(interaction)


@bot.tree.command(name="reload", description="Recharge les fichiers de sounds/")
async def reload(interaction: discord.Interaction):
    count = load_sounds()
    await reply(interaction, f"{count} son(s) recharge(s).")


@bot.event
async def on_voice_state_update(member, before, after):
    vc = member.guild.voice_client
    if vc is None or before.channel != vc.channel or before.channel == after.channel:
        return
    if all(m.bot for m in vc.channel.members):
        stop_ambiance(member.guild.id)
        await vc.disconnect()


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return
    if MESSAGES and REPONSES_TEXTE and MOT_ECRIT.search(message.content):
        reponse = random.choice(REPONSES_TEXTE)
        print(f"[texte] '{MOT_CLE}' lu ({message.author.display_name}) -> {reponse}")
        try:
            await message.reply(reponse, mention_author=False)
        except discord.HTTPException as exc:
            print(f"Reponse impossible : {exc}")
    await bot.process_commands(message)


@bot.command(name="ben")
async def ben_prefix(ctx: commands.Context, son: str | None = None):
    if ctx.author.voice is None or ctx.author.voice.channel is None:
        return
    if son is None:
        name = random.choice(list(sounds)) if sounds else None
    else:
        name = son.lower()
    if name not in sounds:
        return
    vc = ctx.voice_client
    if vc is None:
        vc = await ctx.author.voice.channel.connect(cls=voice_client_class())
        start_ambiance(ctx.guild.id, vc)
        start_ecoute(vc)
    elif vc.channel != ctx.author.voice.channel:
        await vc.move_to(ctx.author.voice.channel)
    await play_sound(vc, sounds[name])


@bot.command(name="sons")
async def sons_prefix(ctx: commands.Context):
    await ctx.reply("\n".join(f"- `{n}`" for n in sounds) or "Aucun son.")


@bot.command(name="leave")
async def leave_prefix(ctx: commands.Context):
    stop_ambiance(ctx.guild.id)
    if ctx.voice_client:
        await ctx.voice_client.disconnect()


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN manquant : copie .env.example en .env et colle ton token.")
    bot.run(TOKEN)
