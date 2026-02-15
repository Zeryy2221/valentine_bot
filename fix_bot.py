import asyncio
from aiogram import Bot

BOT_TOKEN = "BOT_TOKEN = "8482264061:AAFnt86CLKyhj31-WPR9HxQcAEyM9hRdEmc"

async def fix_conflict():
    bot = Bot(BOT_TOKEN)

    # 1. Удаляем webhook (если он был)
    await bot.delete_webhook(drop_pending_updates=True)
    print("✅ Webhook удалён, висящие обновления очищены")

    # 2. Проверяем доступ к боту
    me = await bot.get_me()
    print(f"🤖 Бот готов к работе: @{me.username}")

    await bot.session.close()

if __name__ == "__main__":
    asyncio.run(fix_conflict())