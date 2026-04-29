# 🚀 OCI Resilient Provisioner

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.8+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.8+">
  <img src="https://img.shields.io/badge/Oracle_Cloud-F80000?style=for-the-badge&logo=oracle&logoColor=white" alt="Oracle Cloud">
  <img src="https://img.shields.io/badge/Telegram_Bot-26A5E4?style=for-the-badge&logo=telegram&logoColor=white" alt="Telegram Bot">
  <img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="MIT License">
</p>

<p align="center">
  <b>Herramienta de automatización para el aprovisionamiento resiliente de instancias ARM en Oracle Cloud Infrastructure</b>
</p>

---

## 📋 Descripción

**OCI Resilient Provisioner** es un bot de automatización en Python que resuelve un problema real: aprovisionar instancias **ARM A1.Flex** en Oracle Cloud cuando la demanda supera la capacidad disponible en los centros de datos.

En entornos de alta demanda (como el *Free Tier* de Oracle), las peticiones de creación de instancia se rechazan constantemente con el error `"Out of host capacity"`. Esta herramienta automatiza los reintentos de forma inteligente, con control remoto vía **Telegram** y gestión de errores robusta.

### ✅ Resultado Real

> La herramienta completó su objetivo con éxito, aprovisionando una instancia ARM A1.Flex en `eu-paris-1` tras **4.744 intentos automatizados** (~7-8 días de ejecución continua).

<p align="center">
  <img src="img/10_telegram_exito.png" alt="Notificación de éxito en Telegram" width="350">
</p>

---

## ⚡ Características

| Característica | Detalle |
|---|---|
| 🔄 **Reintentos inteligentes** | Motor de reintentos con backoff adaptativo según tipo de error |
| 📱 **Control por Telegram** | Iniciar, pausar, monitorizar el proceso desde el móvil |
| 🌐 **Descubrimiento dinámico de ADs** | Los Availability Domains se consultan vía API (compatible con cualquier región) |
| 🔒 **Seguridad** | Credenciales separadas en `.env`, filtro de usuario autorizado |
| 🧵 **Multihilo** | Bot de Telegram y motor de despliegue en hilos independientes con estado compartido thread-safe |
| 📊 **Monitorización en tiempo real** | Estado, intentos acumulados, tiempo activo y último evento vía `/estado` |

---

## 🏗️ Arquitectura

```
┌─────────────────────────────────────────────────────────────┐
│                    OCI Resilient Provisioner                │
│                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐   │
│  │   Telegram   │◄──►│ Bot Handler  │◄──►│   Deployer   │   │
│  │   (Usuario)  │    │  (Comandos)  │    │    (Hilo)    │   │
│  └──────────────┘    └──────────────┘    └──────┬───────┘   │
│                                                 │           │
│                              ┌──────────────────┘           │
│                              ▼                              │
│                    ┌──────────────────┐                     │
│                    │   OCI SDK (API)  │                     │
│                    │  - Identity      │                     │
│                    │  - Compute       │                     │
│                    └────────┬─────────┘                     │
│                             │                               │
│                             ▼                               │
│                    ┌──────────────────┐                     │
│                    │  Oracle Cloud    │                     │
│                    │  Infrastructure  │                     │
│                    └──────────────────┘                     │
└─────────────────────────────────────────────────────────────┘
```

---

## 🤖 Comandos de Telegram

| Comando | Descripción |
|---|---|
| `/reanudar` | Iniciar o reanudar el despliegue |
| `/parar` | Pausar el despliegue (los intentos se conservan) |
| `/estado` | Ver estado actual, intentos y último evento |
| `/ayuda` | Lista de comandos disponibles |

### Indicadores de estado

| Icono | Estado | Significado |
|---|---|---|
| 🟢 | DESPLEGANDO ACTIVAMENTE | Motor de despliegue en ejecución |
| 🟡 | PARANDO | Terminando ciclo actual antes de pausar |
| 🔴 | DETENIDO | Motor pausado, esperando `/reanudar` |

---

## 🛠️ Instalación y Configuración

### 1. Clonar el repositorio

```bash
git clone https://github.com/DavidGambin/oci-resilient-provisioner
cd oci-resilient-provisioner
```

### 2. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 3. Configurar credenciales

Copia los ficheros de ejemplo y rellena con tus datos:

```bash
cp .env.example .env
cp api.txt.example api.txt
cp instances.txt.example instances.txt
```

Edita cada fichero con tus credenciales reales. Consulta la [documentación completa](DOCUMENTACION.md#13-guía-obtención-de-claves-api-de-oracle-cloud) para obtener cada valor.

### 4. Ejecutar

```bash
python deployer.py
```

El bot arrancará **pausado**. Envía `/reanudar` desde Telegram para iniciar el despliegue.

---

## 📁 Estructura del Proyecto

```
oci-resilient-provisioner/
├── deployer.py              # Script principal (450 líneas)
├── .env.example             # Plantilla de variables de entorno
├── api.txt.example          # Plantilla de configuración OCI SDK
├── instances.txt.example    # Plantilla de IDs de recursos OCI
├── requirements.txt         # Dependencias Python
├── DOCUMENTACION.md         # Documentación técnica completa
├── LICENSE                  # Licencia MIT
├── .gitignore               # Exclusión de ficheros sensibles
└── img/                     # Capturas para la documentación
    ├── 01_compute_instances.png
    ├── 02_instance_capacity.png
    ├── ...
    └── 10_telegram_exito.png
```

---

## 🔧 Gestión de Errores

El deployer maneja automáticamente los errores de la API de Oracle:

| Error | Acción | Espera |
|---|---|---|
| `500` — Out of host capacity | Reintenta en el siguiente AD | 125-145s (aleatorio) |
| `429` — Rate limiting | Enfriamiento | 3 minutos |
| `400` — LimitExceeded | Detiene el deployer (instancia ya existe) | — |
| Otro `ServiceError` | Reintenta | 60s |

---

## 📄 Especificaciones de la Instancia

| Parámetro | Valor |
|---|---|
| **Shape** | `VM.Standard.A1.Flex` |
| **OCPUs** | 4 |
| **Memoria** | 24 GB RAM |
| **Disco** | 200 GB Boot Volume |
| **IP Pública** | Sí (asignada automáticamente) |

---

## 📖 Documentación

La documentación técnica completa del proyecto está disponible en [DOCUMENTACION.md](DOCUMENTACION.md), incluyendo:

- Arquitectura y modelo de concurrencia
- Explicación detallada de cada sección del código
- Guía paso a paso para obtener las claves API de Oracle Cloud
- Capturas de pantalla del proceso de configuración
- Resultado final con prueba de funcionamiento

---

## ⚠️ Requisitos Previos

- **Python 3.8+**
- **Cuenta de Oracle Cloud** (Free Tier válida)
- **Bot de Telegram** creado vía [@BotFather](https://t.me/BotFather)
- **API Key de OCI** generada y registrada
- **VCN + Subnet** configurados en Oracle Cloud
- **Par de claves SSH** para acceso a la instancia

---

## 📝 Licencia

Este proyecto está bajo la [Licencia MIT](LICENSE).

---

<p align="center">
  <i>Desarrollado por David — Abril 2026</i>
</p>
