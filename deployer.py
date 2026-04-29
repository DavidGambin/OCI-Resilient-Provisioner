"""
╔══════════════════════════════════════════════════════════════════╗
║         OCI RESILIENT PROVISIONER v2.2 — by David                ║
║   Despliegue automático de instancia ARM A1.Flex (4 OCPUs / 24GB)║
║   ADs descubiertos en tiempo real via API (no hardcodeados)      ║
║   Control remoto completo vía Telegram                           ║
╚══════════════════════════════════════════════════════════════════╝

REQUISITOS:
    pip install oci pyTelegramBotAPI python-dotenv

CONFIGURACIÓN:
    Crea un fichero .env en la misma carpeta con estas variables:
    (NUNCA subas el .env a GitHub ni lo compartas)

        TELEGRAM_TOKEN=tu_token_aqui
        TELEGRAM_CHAT_ID=tu_chat_id_aqui
        OCI_CONFIG_PATH=C:/ruta/a/api.txt
        OCI_INSTANCES_PATH=C:/ruta/a/instances.txt
        OCI_SSH_KEY_PATH=C:/ruta/a/ssh-key.pub

COMANDOS DE TELEGRAM:
    /reanudar  — Iniciar o reanudar el despliegue
    /parar     — Pausar el despliegue (el contador de intentos se conserva)
    /estado    — Ver estado actual, intentos y último evento
    /ayuda     — Lista de comandos
"""

import oci
import time
import re
import random
import threading
import logging
import os
from datetime import datetime
from dotenv import load_dotenv
import telebot

# ──────────────────────────────────────────────────────────────────
# 0. CARGA DE SECRETOS DESDE .env
# ──────────────────────────────────────────────────────────────────
load_dotenv()

TELEGRAM_TOKEN      = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID")
CONFIG_FILE_PATH    = os.getenv("OCI_CONFIG_PATH")
INSTANCES_FILE_PATH = os.getenv("OCI_INSTANCES_PATH")
SSH_PUBLIC_KEY_PATH = os.getenv("OCI_SSH_KEY_PATH")
CONFIG_PROFILE      = "DEFAULT"

# ──────────────────────────────────────────────────────────────────
# 1. VALIDACIÓN DE ARRANQUE
# ──────────────────────────────────────────────────────────────────
_REQUIRED = {
    "TELEGRAM_TOKEN":      TELEGRAM_TOKEN,
    "TELEGRAM_CHAT_ID":    TELEGRAM_CHAT_ID,
    "OCI_CONFIG_PATH":     CONFIG_FILE_PATH,
    "OCI_INSTANCES_PATH":  INSTANCES_FILE_PATH,
    "OCI_SSH_KEY_PATH":    SSH_PUBLIC_KEY_PATH,
}
_missing = [k for k, v in _REQUIRED.items() if not v]
if _missing:
    raise SystemExit(
        f"❌ Faltan variables de entorno: {', '.join(_missing)}\n"
        f"   Crea un fichero .env con esas variables."
    )

# ──────────────────────────────────────────────────────────────────
# 2. ESTADO GLOBAL  (protegido con Lock para acceso multi-hilo)
# ──────────────────────────────────────────────────────────────────
_lock            = threading.Lock()
script_corriendo = False
ultima_respuesta = "Bot iniciado. Usa /reanudar para comenzar el despliegue."
total_intentos   = 0
inicio_timestamp = datetime.now()
_hilo_deployer   = None


def _set_estado(respuesta: str, corriendo: bool = True):
    global ultima_respuesta, script_corriendo, total_intentos
    with _lock:
        ultima_respuesta = respuesta
        script_corriendo = corriendo
        if corriendo:
            total_intentos += 1


def _get_estado():
    with _lock:
        return script_corriendo, ultima_respuesta, total_intentos


def _deployer_vivo() -> bool:
    with _lock:
        return _hilo_deployer is not None and _hilo_deployer.is_alive()


def _lanzar_deployer() -> bool:
    global _hilo_deployer, script_corriendo
    with _lock:
        if _hilo_deployer is not None and _hilo_deployer.is_alive():
            return False
        script_corriendo = True
        _hilo_deployer = threading.Thread(target=deployer_oracle, daemon=True)
        _hilo_deployer.start()
    return True


# ──────────────────────────────────────────────────────────────────
# 3. BOT DE TELEGRAM
# ──────────────────────────────────────────────────────────────────
bot = telebot.TeleBot(TELEGRAM_TOKEN)


def _usuario_autorizado(message) -> bool:
    return str(message.chat.id) == TELEGRAM_CHAT_ID


@bot.message_handler(commands=['reanudar'])
def cmd_reanudar(message):
    if not _usuario_autorizado(message):
        return

    if _deployer_vivo():
        bot.reply_to(
            message,
            "⚠️ El deployer *ya está corriendo*.\n"
            "Usa /estado para ver el progreso.",
            parse_mode="Markdown"
        )
        return

    _, ultima, _ = _get_estado()
    if "CONSEGUIDO" in ultima or "LimitExceeded" in ultima:
        bot.reply_to(
            message,
            "🏆 La misión ya fue completada.\n"
            "Si necesitas desplegar de nuevo, reinicia el script desde el servidor.",
        )
        return

    lanzado = _lanzar_deployer()
    if lanzado:
        _, _, intentos_ahora = _get_estado()
        bot.reply_to(
            message,
            f"▶️ *Deployer {'reanudado' if intentos_ahora > 0 else 'iniciado'}.*\n\n"
            f"🔄 Consultando ADs reales de la región via API...\n"
            f"🔁 Intentos acumulados: *{intentos_ahora}*\n\n"
            f"Te avisaré en cuanto haya novedades.",
            parse_mode="Markdown"
        )
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ▶️  Deployer lanzado/reanudado desde Telegram.")
    else:
        bot.reply_to(message, "⚠️ No se pudo lanzar el hilo. Revisa los logs del servidor.")


@bot.message_handler(commands=['parar'])
def cmd_parar(message):
    if not _usuario_autorizado(message):
        return

    if not _deployer_vivo():
        bot.reply_to(message, "ℹ️ El deployer ya estaba detenido.\nUsa /reanudar para activarlo.")
        return

    hora = datetime.now().strftime('%H:%M:%S')
    _set_estado(f"[{hora}] Pausado manualmente por /parar.", corriendo=False)
    bot.reply_to(
        message,
        "🛑 *Deployer pausado.*\n\n"
        "El hilo terminará al final del ciclo actual (máx ~145s).\n"
        "El contador de intentos se conserva.\n"
        "Usa /reanudar para retomar.",
        parse_mode="Markdown"
    )
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 Deployer pausado desde Telegram.")


@bot.message_handler(commands=['start', 'estado'])
def cmd_estado(message):
    if not _usuario_autorizado(message):
        return

    corriendo, ultima, intentos = _get_estado()
    vivo = _deployer_vivo()
    tiempo_proceso = str(datetime.now() - inicio_timestamp).split('.')[0]

    if corriendo and vivo:
        icono, estado_txt = "🟢", "DESPLEGANDO ACTIVAMENTE"
    elif not corriendo and vivo:
        icono, estado_txt = "🟡", "PARANDO (terminando ciclo actual...)"
    else:
        icono, estado_txt = "🔴", "DETENIDO"

    texto = (
        f"📊 *ESTADO DEL DEPLOYER*\n\n"
        f"{icono} Estado: *{estado_txt}*\n"
        f"🔁 Intentos totales: *{intentos}*\n"
        f"⏱ Proceso activo desde hace: *{tiempo_proceso}*\n\n"
        f"📝 *Último evento:*\n`{ultima}`"
    )
    bot.reply_to(message, texto, parse_mode="Markdown")


@bot.message_handler(commands=['ayuda'])
def cmd_ayuda(message):
    if not _usuario_autorizado(message):
        return
    texto = (
        "🤖 *Comandos disponibles:*\n\n"
        "/reanudar — Iniciar o reanudar el despliegue\n"
        "/parar    — Pausar el despliegue (intentos se conservan)\n"
        "/estado   — Estado actual, intentos y último evento\n"
        "/ayuda    — Este mensaje"
    )
    bot.reply_to(message, texto, parse_mode="Markdown")


# ──────────────────────────────────────────────────────────────────
# 4. EXTRACCIÓN DE VARIABLES DEL FICHERO DE INSTANCIAS
# ──────────────────────────────────────────────────────────────────
def extraer_variables_de_instancia(ruta_archivo: str):
    with open(ruta_archivo, 'r') as f:
        contenido = f.read()

    def _extraer(campo):
        m = re.search(rf'{campo}:\s*"?([^"\n]+)"?', contenido)
        if not m:
            raise ValueError(f"Campo '{campo}' no encontrado en {ruta_archivo}")
        return m.group(1).strip()

    return (
        _extraer("compartmentId"),
        _extraer("subnetId"),
        _extraer("imageId"),
    )


# ──────────────────────────────────────────────────────────────────
# 5. DESCUBRIMIENTO REAL DE AVAILABILITY DOMAINS VÍA API
#
#    En lugar de construir los nombres matemáticamente (que fue el
#    error de v2.0/v2.1), consultamos directamente a Oracle cuántos
#    ADs existen en nuestra región y tenancy.
#
#    Regiones con 1 AD (París, Madrid, Milán...): devuelve 1 elemento.
#    Regiones con 3 ADs (Frankfurt, Ashburn...):  devuelve 3 elementos.
#    El script funciona igual en ambos casos sin tocar nada.
# ──────────────────────────────────────────────────────────────────
def obtener_availability_domains(config: dict, compartment_id: str) -> list:
    """
    Consulta la API de Identity de Oracle para obtener los ADs
    reales disponibles en la región de la cuenta.
    """
    identity_client = oci.identity.IdentityClient(config)
    response = identity_client.list_availability_domains(compartment_id=compartment_id)
    nombres = [ad.name for ad in response.data]
    if not nombres:
        raise ValueError("La API de Oracle no devolvió ningún Availability Domain.")
    return nombres


# ──────────────────────────────────────────────────────────────────
# 6. CONSTRUCTOR DE LaunchInstanceDetails
# ──────────────────────────────────────────────────────────────────
def construir_detalles(compartment, subnet, image, ssh_key, availability_domain):
    return oci.core.models.LaunchInstanceDetails(
        compartment_id=compartment,
        availability_domain=availability_domain,
        shape="VM.Standard.A1.Flex",
        shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
            ocpus=4,
            memory_in_gbs=24
        ),
        source_details=oci.core.models.InstanceSourceViaImageDetails(
            source_type="image",
            image_id=image,
            boot_volume_size_in_gbs=200
        ),
        create_vnic_details=oci.core.models.CreateVnicDetails(
            subnet_id=subnet,
            assign_public_ip=True
        ),
        display_name="DAVID-SERVER-ARM",
        metadata={"ssh_authorized_keys": ssh_key}
    )


# ──────────────────────────────────────────────────────────────────
# 7. MOTOR PRINCIPAL — EL DEPLOYER
# ──────────────────────────────────────────────────────────────────
def deployer_oracle():

    # ── Carga de recursos ─────────────────────────────────────────
    try:
        config = oci.config.from_file(
            file_location=CONFIG_FILE_PATH,
            profile_name=CONFIG_PROFILE
        )
        compartment, subnet, image = extraer_variables_de_instancia(INSTANCES_FILE_PATH)
        compute_client = oci.core.ComputeClient(config)

        with open(SSH_PUBLIC_KEY_PATH, 'r') as kf:
            ssh_public_key = kf.read().strip()

        # ── Descubrimiento real de ADs ────────────────────────────
        availability_domains = obtener_availability_domains(config, compartment)

    except Exception as e:
        msg = f"❌ Error de arranque: {e}"
        print(msg)
        _set_estado(msg, corriendo=False)
        try:
            bot.send_message(
                TELEGRAM_CHAT_ID,
                f"💀 *El deployer no pudo arrancar:*\n`{e}`",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return

    print(f"✅ ADs reales confirmados por la API de Oracle:")
    for ad in availability_domains:
        print(f"   → {ad}")
    print(f"   Total: {len(availability_domains)} AD(s) en esta región.\n")

    # ── Bucle de despliegue ────────────────────────────────────────
    ad_index = 0

    while True:
        corriendo, _, intentos = _get_estado()
        if not corriendo:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 Hilo del deployer terminando limpiamente.")
            break

        ad_actual = availability_domains[ad_index % len(availability_domains)]
        ad_index += 1
        hora = datetime.now().strftime('%H:%M:%S')
        print(f"[{hora}] Intento #{intentos + 1} → {ad_actual}")

        try:
            detalles = construir_detalles(
                compartment, subnet, image, ssh_public_key, ad_actual
            )
            compute_client.launch_instance(detalles)

            # ── 🎉 ÉXITO ──────────────────────────────────────────
            _, _, intentos_finales = _get_estado()
            _set_estado(f"[{hora}] ¡CONSEGUIDO en {ad_actual}!", corriendo=False)
            bot.send_message(
                TELEGRAM_CHAT_ID,
                f"🚨 ¡¡INSTANCIA APROVISIONADA!! 🚨\n\n"
                f"✅ Instancia ARM creada en: `{ad_actual}`\n"
                f"🔁 Total de intentos: *{intentos_finales}*\n\n"
                f"👉 Entra al panel de Oracle Cloud ahora mismo.",
                parse_mode="Markdown"
            )
            print("\n" + "=" * 55)
            print(f"🎉 ¡ÉXITO! INSTANCIA CREADA EN {ad_actual}")
            print("=" * 55 + "\n")
            break

        except oci.exceptions.ServiceError as e:
            hora = datetime.now().strftime('%H:%M:%S')

            if e.status == 500 and "Out of host capacity" in e.message:
                espera = random.randint(125, 145)
                msg = f"[{hora}] Sin capacidad → espera {espera}s"
                _set_estado(msg)
                print(msg)
                time.sleep(espera)

            elif e.status == 429:
                msg = f"[{hora}] Rate limit (429) → enfriando 3 min"
                _set_estado(msg)
                print(msg)
                time.sleep(180)

            elif e.status == 400 and "LimitExceeded" in str(e.code):
                msg = f"[{hora}] LimitExceeded: puede que la instancia ARM ya exista"
                _set_estado(msg, corriendo=False)
                print(msg)
                bot.send_message(
                    TELEGRAM_CHAT_ID,
                    "⚠️ *LimitExceeded*\n\n"
                    "Oracle dice que ya tienes el límite de instancias ARM cubierto.\n"
                    "Revisa el panel: puede que la máquina *ya exista*.",
                    parse_mode="Markdown"
                )
                break

            else:
                msg = f"[{hora}] ServiceError {e.status}: {e.message}"
                _set_estado(msg)
                print(msg)
                time.sleep(60)

        except Exception as e:
            hora = datetime.now().strftime('%H:%M:%S')
            msg = f"[{hora}] ⚠️ {type(e).__name__}: {e}. Reintentando en 60s..."
            _set_estado(msg)
            print(msg)
            time.sleep(60)


# ──────────────────────────────────────────────────────────────────
# 8. PUNTO DE ENTRADA
# ──────────────────────────────────────────────────────────────────
def main():
    print("╔══════════════════════════════════════════════════════╗")
    print("║     OCI RESILIENT PROVISIONER v2.2 — Arrancando     ║")
    print("╚══════════════════════════════════════════════════════╝\n")
    print("El deployer arranca PAUSADO. Usa /reanudar en Telegram.\n")

    telebot.logger.setLevel(logging.CRITICAL)

    try:
        bot.send_message(
            TELEGRAM_CHAT_ID,
            "🚀 *OCI Resilient Provisioner v2.2 en línea*\n\n"
            "✅ ADs consultados en tiempo real (no hardcodeados)\n\n"
            "El deployer arranca *pausado*.\n\n"
            "▶️ /reanudar — Comenzar el despliegue\n"
            "🛑 /parar    — Pausar\n"
            "📊 /estado   — Ver progreso\n"
            "❓ /ayuda    — Todos los comandos",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"❌ No se pudo conectar a Telegram: {e}")
        print("   Verifica TELEGRAM_TOKEN y TELEGRAM_CHAT_ID en tu .env")
        return

    while True:
        try:
            bot.infinity_polling(
                timeout=60,
                long_polling_timeout=60,
                logger_level=logging.CRITICAL
            )
        except Exception:
            time.sleep(15)


if __name__ == "__main__":
    main()
