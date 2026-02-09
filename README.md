# 💰 GastosBot — Control de Gastos por Telegram

Bot personal de Telegram para registrar gastos e ingresos desde el celular en segundos.

## ⚡ Registro Rápido

Escribe solo el monto en el chat y el bot te guía:

```
150           → selecciona categoría → método de pago → ✅
85 almuerzo   → con descripción automática
```

## 🚀 Setup (5 minutos)

### 1. Crear el bot en Telegram

1. Abre Telegram y busca **@BotFather**
2. Envía `/newbot`
3. Elige nombre: `Mi Control de Gastos`
4. Elige username: `mi_gastos_bot` (debe terminar en `bot`)
5. Copia el **token** que te da

### 2. Obtener tu User ID

1. Busca **@userinfobot** en Telegram
2. Envíale cualquier mensaje
3. Copia tu **ID numérico**

### 3. Configurar y desplegar

```bash
# Clonar/copiar archivos al VPS
scp -r gastosbot/ user@tu-vps:/home/user/gastosbot/

# En el VPS
cd gastosbot

# Crear archivo .env
cp .env.example .env
nano .env
# Pegar tu TELEGRAM_BOT_TOKEN y AUTHORIZED_USERS

# Levantar
docker compose up -d

# Ver logs
docker compose logs -f
```

### 4. Probar

Abre tu bot en Telegram y envía `/start`

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

## 💳 Métodos de Pago

Incluye Yape, BCP, Plin, Efectivo, Tarjeta y Transferencia.

## 🏷️ Categorías por Defecto

**Gastos:** Vivienda, Comida, Transporte, Servicios, Salud, Educación, Entretenimiento, Ropa, Ahorro, Otros

**Ingresos:** Salario, Freelance, Inversiones, Rentas, Otros

## 🔒 Seguridad

- Solo usuarios autorizados pueden usar el bot (configurable en `.env`)
- Los datos se guardan en SQLite en tu propio VPS
- No se envía información a terceros

## 🗂️ Estructura

```
gastosbot/
├── bot.py              # Bot principal
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── data/
    └── gastos.db       # Base de datos (se crea automáticamente)
```

## 🔧 Mantenimiento

```bash
# Reiniciar bot
docker compose restart

# Actualizar código
docker compose down
docker compose up -d --build

# Backup de datos
cp data/gastos.db data/gastos_backup_$(date +%Y%m%d).db
```
