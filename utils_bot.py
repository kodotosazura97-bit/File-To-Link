import os
import asyncio
import re
from telethon import TelegramClient, events, Button
from aiohttp import web

# --- CONFIG ---
API_ID = 22446373
API_HASH = 'cee6afd906c49dd7314e4f2db862fea3'
BOT_TOKEN = '8342242559:AAHTzLR4fDaV3uF1fR5vxrpjWcPi_Mkhyf4'
DATABASE_CHANNEL = -1003543256849
PORT = int(os.environ.get("PORT", 10000))
BASE_URL = "https://move-1ofw.onrender.com"

# --- HELPERS ---
def parse_range(range_header, file_size):
    """Parses 'bytes=start-end' for resume support."""
    if not range_header:
        return 0, file_size - 1
    match = re.match(r'bytes=(\d+)-(\d*)', range_header)
    if not match:
        return 0, file_size - 1
    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else file_size - 1
    return start, min(end, file_size - 1)

# 1. WEB HANDLERS
async def home_handler(request):
    """Fixes the 404 error for Render health checks and cron-job."""
    return web.Response(text="✅ Bot is Running with Resume Support!", status=200)

async def stream_handler(request):
    client = request.app['client']
    msg_id = int(request.match_info['file_id'])
    range_header = request.headers.get('Range')

    try:
        msg = await client.get_messages(DATABASE_CHANNEL, ids=msg_id)
        if not msg or not msg.file:
            return web.Response(text="File not found", status=404)

        file_size = msg.file.size
        start, end = parse_range(range_header, file_size)
        
        # Telegram seeks must be multiples of 4096 bytes
        offset = (start // 4096) * 4096
        skip = start - offset
        length_to_send = end - start + 1

        headers = {
            'Content-Type': msg.file.mime_type or "application/octet-stream",
            'Content-Disposition': f'attachment; filename="{msg.file.name or "file"}"',
            'Accept-Ranges': 'bytes',
            'Content-Range': f'bytes {start}-{end}/{file_size}',
            'Content-Length': str(length_to_send),
        }

        # Status 206 means "Partial Content" which enables resuming
        response = web.StreamResponse(status=206 if range_header else 200, headers=headers)
        await response.prepare(request)

        current_sent = 0
        async for chunk in client.iter_download(msg.media, offset=offset, chunk_size=1024*1024):
            if skip > 0:
                if len(chunk) <= skip:
                    skip -= len(chunk)
                    continue
                else:
                    chunk = chunk[skip:]
                    skip = 0
            
            if current_sent + len(chunk) > length_to_send:
                chunk = chunk[:length_to_send - current_sent]
            
            await response.write(chunk)
            current_sent += len(chunk)
            
            if current_sent >= length_to_send:
                break
                
        return response
    except Exception as e:
        return web.Response(text=f"Error: {e}", status=500)

# 2. BOT HANDLERS
async def setup_bot_handlers(client):
    @client.on(events.NewMessage(pattern='/start'))
    async def start(event):
        await event.reply("🚀 **Bot is Online!**\nSend me a file to get a resumable link.")

    @client.on(events.NewMessage(func=lambda e: e.file and e.is_private))
    async def handle_file(event):
        db_msg = await event.message.forward_to(DATABASE_CHANNEL)
        link = f"{BASE_URL}/dl/{db_msg.id}"
        await event.reply(
            f"✅ **Link Generated!**\nSize: {round(event.file.size / (1024*1024), 2)} MB\n\n"
            f"⚡ *Resume Support Enabled*",
            buttons=[Button.url("📥 Download Now", link)]
        )

# 3. MAIN RUNNER
async def run():
    client = TelegramClient('bot_session', API_ID, API_HASH)
    await client.start(bot_token=BOT_TOKEN)
    await setup_bot_handlers(client)

    app = web.Application()
    app['client'] = client
    app.add_routes([
        web.get('/', home_handler), # Home route to prevent 404
        web.get('/dl/{file_id}', stream_handler)
    ])
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    
    print("---------------------------------------")
    print("✅ BOT IS RUNNING WITH RESUME SUPPORT!")
    print(f"🔗 URL: {BASE_URL}")
    print("---------------------------------------")

    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(run())
