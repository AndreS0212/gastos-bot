# 💰 GastosBot — Control de Gastos por Telegram + Google Sheets

Bot personal para registrar gastos e ingresos desde Telegram en segundos. Cada registro se sincroniza automáticamente con Google Sheets.

Hecho para Perú: Soles (S/), Yape, BCP, Plin.

## ⚡ Registro Rápido (3 taps)

```
Tú:  45
Bot: ⚡ Gasto: S/45.00 → [categorías]
Tú:  🍽️ Comida
Bot: 💳 [Yape] [BCP] [Plin] [Efectivo]...
Tú:  Yape
Bot: ✅ Registrado — Total hoy: S/45.00
     📋 Sincronizado con Google Sheets
```

Con descripción: `85 almuerzo`  
Con foto: 📸 envía foto de boleta + monto en caption

## 📋 Comandos

| Comando | Descripción |
|---------|-------------|
| `/start` | Inicio + resumen del mes |
| `/gasto` | Registrar gasto paso a paso |
| `/ingreso` | Registrar ingreso |
| `/resumen` | Resumen mensual con gráficas |
| `/hoy` | Gastos del día |
| `/recientes` | Últimos 10 movimientos |
| `/borrar` | Eliminar último registro |
| `/fijo` | Agregar gasto/ingreso fijo mensual |
| `/fijos` | Ver todos los fijos activos |
| `/quitarfijo` | Desactivar un fijo |

## 🔄 Gastos e Ingresos Fijos

Configura pagos recurrentes que se registran **automáticamente** cada mes:
- Renta, servicios, suscripciones
- Salario, freelance, rentas

El bot notifica a las 8:00 AM (hora Lima) cuando registra un fijo.

## 📸 Fotos de Boletas

Envía una foto de tu boleta directamente al bot:
- Con caption `45 almuerzo` → registra gasto + guarda foto
- Sin caption → te pide el monto

## 🚀 Setup

### 1. Crear bot en Telegram
1. Busca **@BotFather** → `/newbot`
2. Copia el **token**
3. Busca **@userinfobot** → copia tu **ID numérico**

### 2. Configurar Google Sheets

1. Ve a [console.cloud.google.com](https://console.cloud.google.com)
2. Crea un proyecto → activa **Google Sheets API**
3. **APIs & Services → Credentials → Create Credentials → Service Account**
4. Nombre: `gastosbot` → Done
5. Entra a la service account → **Keys → Add Key → JSON** → descarga el archivo
6. Sube el Excel `Control_Gastos_Peru_2026.xlsx` a Google Drive → ábrelo como Google Sheet
7. En el Sheet → **Compartir** → pega el `client_email` del JSON como **Editor**
8. Copia el **ID del Sheet** (parte entre `/d/` y `/edit` en la URL)

### 3. Desplegar

#### Con Coolify (desde GitHub)
1. Source → GitHub → `AndreS0212/gastos-bot`
2. Build Pack → Docker Compose
3. Environment Variables:
```
TELEGRAM_BOT_TOKEN=tu_token
AUTHORIZED_USERS=tu_telegram_id
GOOGLE_SHEETS_ID=id_del_sheet
GOOGLE_CREDENTIALS_JSON={"type":"service_account","project_id":"...todo el json en una línea..."}
```
4. Deploy 🚀

#### Con Docker directo
```bash
cd gastos-bot
cp .env.example .env
nano .env  # configurar variables
docker compose up -d
```

### 4. Probar
Abre tu bot en Telegram → `/start` → debe mostrar "✅ Google Sheets conectado"

## 💳 Métodos de Pago
Yape · BCP · Plin · Efectivo · Tarjeta · Transferencia

## 🏷️ Categorías

**Gastos:** Vivienda, Comida, Transporte, Servicios, Salud, Educación, Entretenimiento, Ropa, Ahorro, Otros

**Ingresos:** Salario, Freelance, Inversiones, Rentas, Otros

## 🗂️ Estructura

```
gastos-bot/
├── bot.py              # Bot principal
├── sheets_sync.py      # Sincronización con Google Sheets
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── .gitignore
└── data/               (se crea automáticamente)
    ├── gastos.db
    └── photos/
```

## 🔧 Mantenimiento

```bash
# Reiniciar
docker compose restart

# Actualizar (después de git pull)
docker compose down
docker compose up -d --build

# Backup
cp data/gastos.db data/backup_$(date +%Y%m%d).db

# Ver logs
docker compose logs -f gastosbot
```

## 🔒 Seguridad
- Solo usuarios autorizados (tu Telegram ID)
- Datos en SQLite + Google Sheets (doble respaldo)
- Fotos almacenadas localmente en tu VPS
- Service account con acceso solo a tu Sheet
