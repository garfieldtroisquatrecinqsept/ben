import asyncio
import collections
import os
import sys

import discord
from discord.ext import voice_recv

import bot as b

DUREE = 60

ops_vus: collections.Counter = collections.Counter()
payloads: dict[int, set] = collections.defaultdict(set)
paquets = collections.Counter()
dechiffrements = collections.Counter()
erreurs: list[str] = []


def instrumenter_gateway():
    from discord.ext.voice_recv import gateway as vr_gateway

    hook_original = vr_gateway.hook

    async def hook_espion(self, msg):
        op = msg.get("op")
        ops_vus[op] += 1
        payloads[op] |= set(msg.get("d", {}) or {})
        try:
            await hook_original(self, msg)
        except Exception as exc:
            erreurs.append(f"hook op {op} : {type(exc).__name__}: {exc}")

    vr_gateway.hook = hook_espion


def instrumenter_decodeur():
    import davey
    from discord.ext.voice_recv import opus as vr_opus

    decode_original = vr_opus.PacketDecoder._decode_packet

    def decode_espion(self, packet):
        paquets["total"] += 1
        vc = self.sink.voice_client
        session = getattr(vc._connection, "dave_session", None)
        user_id = vc._get_id_from_ssrc(self.ssrc)

        paquets["ssrc_connu" if user_id else "ssrc_inconnu"] += 1
        if session is None:
            paquets["sans_session_dave"] += 1
        elif not session.ready:
            paquets["session_pas_prete"] += 1

        if packet and session is not None and session.ready and user_id is not None:
            try:
                clair = session.decrypt(user_id, davey.MediaType.audio, packet.decrypted_data)
                if clair:
                    dechiffrements["ok"] += 1
                    packet.decrypted_data = clair
                else:
                    dechiffrements["vide"] += 1
                    return packet, b""
            except Exception as exc:
                dechiffrements["echec"] += 1
                msg = f"decrypt : {type(exc).__name__}: {exc}"
                if msg not in erreurs:
                    erreurs.append(msg)
                return packet, b""
        try:
            return decode_original(self, packet)
        except Exception as exc:
            msg = f"opus : {type(exc).__name__}: {exc}"
            if msg not in erreurs:
                erreurs.append(msg)
            return packet, b""

    vr_opus.PacketDecoder._decode_packet = decode_espion


def rapport(vc):
    print("\n" + "=" * 62)
    print("RAPPORT")
    print("=" * 62)
    print("\nMessages du serveur vocal (op -> nombre, cles du payload) :")
    for op, n in sorted(ops_vus.items(), key=lambda kv: -kv[1]):
        print(f"   op {op:>3} x{n:<5} {sorted(payloads[op])}")

    print("\nAssociation flux audio -> utilisateur :")
    table = getattr(vc, "_ssrc_to_id", {})
    print(f"   table ssrc -> user_id : {dict(table) or 'VIDE'}")

    session = getattr(vc._connection, "dave_session", None)
    print("\nChiffrement de bout en bout (DAVE) :")
    print(f"   version negociee : {vc._connection.dave_protocol_version}")
    print(f"   session presente : {session is not None}")
    if session is not None:
        print(f"   session prete    : {session.ready}")
        print(f"   membres connus   : {session.get_user_ids()}")

    print("\nPaquets audio :")
    if not paquets["total"]:
        print("   AUCUN paquet recu - personne n'a parle, ou le flux n'arrive pas")
    for cle, n in paquets.items():
        print(f"   {cle:<20} {n}")
    print("\nDechiffrement :")
    print(f"   {dict(dechiffrements) or 'jamais tente'}")

    if erreurs:
        print("\nErreurs rencontrees :")
        for e in erreurs:
            print(f"   - {e}")
    print("=" * 62)


async def main():
    b.load_sounds()
    instrumenter_gateway()
    instrumenter_decodeur()

    @b.bot.event
    async def on_ready():
        try:
            salon = None
            for guild in b.bot.guilds:
                for membre in guild.members if guild.members else []:
                    if membre.voice and membre.voice.channel and not membre.bot:
                        salon = membre.voice.channel
                        break
            if salon is None:
                gid = int(b.GUILD_ID)
                guild = b.bot.get_guild(gid)
                salons = [c for c in guild.voice_channels if any(not m.bot for m in c.members)]
                salon = salons[0] if salons else None
            if salon is None:
                print("Aucun salon vocal occupe. Mets-toi dans un vocal et relance.")
                return

            print(f"Je rejoins {salon.name} - PARLE PENDANT {DUREE} SECONDES")
            vc = await salon.connect(cls=voice_recv.VoiceRecvClient)
            vc.listen(voice_recv.BasicSink(lambda user, data: None))
            for reste in range(DUREE, 0, -10):
                print(f"   ... {reste}s (paquets recus : {paquets['total']})")
                await asyncio.sleep(10)
            rapport(vc)
            await vc.disconnect()
        except Exception as exc:
            import traceback

            traceback.print_exc()
        finally:
            await b.bot.close()

    await b.bot.start(b.TOKEN)


if __name__ == "__main__":
    if not b.TOKEN:
        sys.exit("DISCORD_TOKEN manquant")
    asyncio.run(main())
