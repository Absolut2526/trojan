import base64
import io
import logging
from typing import Optional, Union
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, BufferedInputFile

from config import config
from connection_manager import manager

logger = logging.getLogger(__name__)

bot: Optional[Bot] = None
dp = Dispatcher()

class AdminStates(StatesGroup):
    waiting_for_url = State()
    waiting_for_process_name = State()

def is_authorized(event: Union[types.Message, types.CallbackQuery]) -> bool:
    allowed = config.ALLOWED_CHAT_IDS + config.ADMIN_IDS
    if not allowed:
        return True

    if isinstance(event, types.CallbackQuery):
        chat_id = event.message.chat.id if event.message else event.from_user.id
        user_id = event.from_user.id
    else:
        chat_id = event.chat.id
        user_id = event.from_user.id if event.from_user else 0

    return (chat_id in allowed) or (user_id in allowed)

def get_online_pcs():
    """Повертає список онлайн комп'ютерів, відсортований за номером як на сайті."""
    pcs = manager.get_all_pcs()
    online = [(name, data) for name, data in pcs.items() if data.get("status") == "online"]

    def sort_key(item):
        name = item[0]
        digits = "".join(ch for ch in name if ch.isdigit())
        num = int(digits) if digits else 0
        return (num, name)

    return sorted(online, key=sort_key)

def build_main_menu_text() -> str:
    online_pcs = get_online_pcs()
    online_count = len(online_pcs)

    if online_count == 0:
        return (
            "🎮 <b>Панель керування ПК-клубом</b>\n\n"
            "🔌 <b>Усі комп'ютери вимкнені</b>\n"
            "Комп'ютер автоматично з'явиться тут, щойно його увімкнуть.\n\n"
            "📊 Онлайн: <b>0</b> комп'ютерів"
        )

    return (
        "🎮 <b>Панель керування ПК-клубом</b>\n\n"
        f"📊 Онлайн: <b>{online_count}</b> комп'ютерів\n\n"
        "Оберіть ПК зі списку нижче або скористайтесь швидкими командами:\n"
        "• <code>/screen PC-01</code> — скріншот\n"
        "• <code>/open PC-01 https://url</code> — відкрити сайт\n"
        "• <code>/kill PC-01 dota2.exe</code> — закрити процес\n"
        "• <code>/procs PC-01</code> — список процесів"
    )

def get_pc_list_keyboard() -> InlineKeyboardMarkup:
    online_pcs = get_online_pcs()
    buttons = []
    row = []

    for idx, (name, data) in enumerate(online_pcs, start=1):
        btn_text = f"🟢 №{idx} ({name})"
        row.append(InlineKeyboardButton(text=btn_text, callback_data=f"pc:{name}"))
        if len(row) == 2:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    if online_pcs:
        buttons.append([
            InlineKeyboardButton(text="🔄 Рестарт ВСІХ", callback_data="mass:restart_confirm"),
            InlineKeyboardButton(text="⏻ Вимкнути ВСІ", callback_data="mass:shutdown_confirm")
        ])
    buttons.append([InlineKeyboardButton(text="🔄 Оновити список", callback_data="refresh_list")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_pc_actions_keyboard(pc_name: str, is_online: bool = True) -> InlineKeyboardMarkup:
    if not is_online:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 До списку ПК", callback_data="back_to_list")]
        ])

    keyboard = [
        [
            InlineKeyboardButton(text="📸 Скріншот", callback_data=f"act:screenshot:{pc_name}"),
            InlineKeyboardButton(text="📋 Процеси", callback_data=f"act:procs:{pc_name}")
        ],
        [
            InlineKeyboardButton(text="🌐 Відкрити URL", callback_data=f"act:open_url:{pc_name}"),
            InlineKeyboardButton(text="🖼 Картинка", callback_data=f"act:pic_prompt:{pc_name}")
        ],
        [
            InlineKeyboardButton(text="❌ Закрити процес", callback_data=f"act:kill_proc:{pc_name}"),
            InlineKeyboardButton(text="🔄 Перезавантажити", callback_data=f"act:restart_confirm:{pc_name}")
        ],
        [
            InlineKeyboardButton(text="⏻ Вимкнути", callback_data=f"act:shutdown_confirm:{pc_name}"),
            InlineKeyboardButton(text="🔙 До списку ПК", callback_data="back_to_list")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# --- /start & /menu ---
@dp.message(CommandStart())
@dp.message(Command("menu"))
async def cmd_start(message: types.Message):
    if not is_authorized(message):
        return

    text = build_main_menu_text()
    await message.answer(text, parse_mode="HTML", reply_markup=get_pc_list_keyboard())

# --- Швидкі команди для груп (/screen, /open, /kill, /procs, /restart, /shutdown) ---
@dp.message(Command("screen"))
async def cmd_quick_screenshot(message: types.Message, command: CommandObject):
    if not is_authorized(message):
        return
    pc_name = (command.args or "").strip()
    if not pc_name:
        await message.reply("⚠️ Вкажіть ім'я ПК: <code>/screen PC-01</code>", parse_mode="HTML")
        return

    status_msg = await message.reply(f"⏳ Отримання знімка екрану з <b>{pc_name}</b>...", parse_mode="HTML")
    resp = await manager.send_command(pc_name, "screenshot", timeout=12.0)
    if resp.get("status") == "ok" and "image_base64" in resp:
        image_bytes = base64.b64decode(resp["image_base64"])
        photo_file = BufferedInputFile(image_bytes, filename=f"screen_{pc_name}.jpg")
        await message.reply_photo(photo_file, caption=f"📸 Екран <b>{pc_name}</b>", parse_mode="HTML")
        await status_msg.delete()
    else:
        err = resp.get("message", "Помилка")
        await status_msg.edit_text(f"❌ Не вдалося отримати скріншот з {pc_name}: {err}")

@dp.message(Command("open"))
async def cmd_quick_open_url(message: types.Message, command: CommandObject):
    if not is_authorized(message):
        return
    args = (command.args or "").strip().split(maxsplit=1)
    if len(args) < 2:
        await message.reply("⚠️ Формат: <code>/open PC-01 https://youtube.com</code>", parse_mode="HTML")
        return
    pc_name, url = args[0], args[1]
    if not (url.startswith("http://") or url.startswith("https://")):
        url = "https://" + url

    msg = await message.reply(f"⏳ Відкриваю {url} на <b>{pc_name}</b>...", parse_mode="HTML")
    resp = await manager.send_command(pc_name, "open_url", {"url": url}, timeout=6.0)
    if resp.get("status") == "ok":
        await msg.edit_text(f"✅ Посилання успішно відкрито на <b>{pc_name}</b>: {url}", parse_mode="HTML")
    else:
        await msg.edit_text(f"❌ Помилка на {pc_name}: {resp.get('message')}")

@dp.message(Command("kill"))
async def cmd_quick_kill_proc(message: types.Message, command: CommandObject):
    if not is_authorized(message):
        return
    args = (command.args or "").strip().split(maxsplit=1)
    if len(args) < 2:
        await message.reply("⚠️ Формат: <code>/kill PC-01 dota2.exe</code>", parse_mode="HTML")
        return
    pc_name, proc_name = args[0], args[1]
    msg = await message.reply(f"⏳ Завершую <code>{proc_name}</code> на <b>{pc_name}</b>...", parse_mode="HTML")
    resp = await manager.send_command(pc_name, "kill_process", {"name": proc_name}, timeout=6.0)
    if resp.get("status") == "ok":
        killed_count = resp.get("killed_count", 1)
        await msg.edit_text(f"✅ Процес <code>{proc_name}</code> закрито на <b>{pc_name}</b> (завершено: {killed_count})", parse_mode="HTML")
    else:
        await msg.edit_text(f"❌ Помилка: {resp.get('message')}")

@dp.message(Command("procs"))
async def cmd_quick_procs(message: types.Message, command: CommandObject):
    if not is_authorized(message):
        return
    pc_name = (command.args or "").strip()
    if not pc_name:
        await message.reply("⚠️ Вкажіть ім'я ПК: <code>/procs PC-01</code>", parse_mode="HTML")
        return

    resp = await manager.send_command(pc_name, "list_processes", timeout=8.0)
    if resp.get("status") == "ok":
        procs = resp.get("processes", [])
        if not procs:
            await message.reply(f"На {pc_name} немає активних процесів.")
            return

        lines = [f"📋 <b>Топ процесів на {pc_name}:</b>"]
        for p in procs[:15]:
            lines.append(f"• <code>{p['name']}</code> (RAM: {p.get('memory', '0')} MB, CPU: {p.get('cpu', 0)}%)")

        await message.reply("\n".join(lines), parse_mode="HTML")
    else:
        await message.reply(f"❌ Помилка: {resp.get('message')}")

# --- Callbacks для меню кнопок ---
@dp.callback_query(F.data == "refresh_list")
async def cb_refresh_list(callback: types.CallbackQuery):
    if not is_authorized(callback):
        await callback.answer("⛔ Доступ заборонено", show_alert=True)
        return

    text = build_main_menu_text()
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_pc_list_keyboard())
    except Exception:
        pass
    await callback.answer("Оновлено 🔄")

@dp.callback_query(F.data == "back_to_list")
async def cb_back_to_list(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await cb_refresh_list(callback)

@dp.callback_query(F.data.startswith("pc:"))
async def cb_pc_detail(callback: types.CallbackQuery, state: FSMContext):
    if not is_authorized(callback):
        await callback.answer("⛔ Доступ заборонено", show_alert=True)
        return
    await state.clear()
    pc_name = callback.data.split(":")[1]
    is_online = manager.is_online(pc_name)

    if not is_online:
        await callback.answer("⚠️ Цей комп'ютер зараз вимкнений", show_alert=True)
        try:
            await callback.message.edit_text(build_main_menu_text(), parse_mode="HTML", reply_markup=get_pc_list_keyboard())
        except Exception:
            pass
        return

    online_pcs = get_online_pcs()
    order_idx = None
    for idx, (name, _) in enumerate(online_pcs, start=1):
        if name == pc_name:
            order_idx = idx
            break

    title = f"№{order_idx} ({pc_name})" if order_idx else pc_name

    info = manager.client_info.get(pc_name, {}).get("info", {})
    cpu = info.get("cpu", "н/д")
    ram = info.get("ram", "н/д")
    os_name = info.get("os", "Windows")

    text = (
        f"🖥 <b>Комп'ютер {title}</b>\n"
        f"Статус: <b>🟢 Онлайн</b>\n"
        f"ОС: {os_name}\n"
        f"CPU: {cpu}% | RAM: {ram}%\n\n"
        "Оберіть дію:"
    )

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=get_pc_actions_keyboard(pc_name, is_online=True)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("act:screenshot:"))
async def cb_screenshot(callback: types.CallbackQuery):
    if not is_authorized(callback):
        return
    pc_name = callback.data.split(":")[2]
    await callback.answer("📸 Роблю скріншот...")
    status_msg = await callback.message.answer(f"⏳ Отримання знімка екрану з <b>{pc_name}</b>...", parse_mode="HTML")

    resp = await manager.send_command(pc_name, "screenshot", timeout=12.0)
    if resp.get("status") == "ok" and "image_base64" in resp:
        image_bytes = base64.b64decode(resp["image_base64"])
        photo_file = BufferedInputFile(image_bytes, filename=f"screen_{pc_name}.jpg")
        await callback.message.answer_photo(photo_file, caption=f"📸 Екран <b>{pc_name}</b>", parse_mode="HTML")
        await status_msg.delete()
    else:
        err = resp.get("message", "Помилка при створенні знімка")
        await status_msg.edit_text(f"❌ Не вдалося отримати скріншот з {pc_name}: {err}")

@dp.callback_query(F.data.startswith("act:procs:"))
async def cb_list_procs(callback: types.CallbackQuery):
    if not is_authorized(callback):
        return
    pc_name = callback.data.split(":")[2]
    await callback.answer("Отримую процеси...")
    
    resp = await manager.send_command(pc_name, "list_processes", timeout=8.0)
    if resp.get("status") == "ok":
        procs = resp.get("processes", [])
        if not procs:
            await callback.message.answer(f"На {pc_name} немає активних процесів.")
            return

        lines = [f"📋 <b>Топ процесів на {pc_name}:</b>"]
        for p in procs[:15]:
            lines.append(f"• <code>{p['name']}</code> (RAM: {p.get('memory', '0')} MB, CPU: {p.get('cpu', 0)}%)")

        await callback.message.answer("\n".join(lines), parse_mode="HTML")
    else:
        await callback.message.answer(f"❌ Помилка: {resp.get('message')}")

@dp.callback_query(F.data.startswith("act:open_url:"))
async def cb_open_url_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_authorized(callback):
        return
    pc_name = callback.data.split(":")[2]
    await state.set_state(AdminStates.waiting_for_url)
    await state.update_data(target_pc=pc_name)
    await callback.message.answer(
        f"🌐 Введіть посилання для відкриття на <b>{pc_name}</b> (або <code>/open {pc_name} url</code>):",
        parse_mode="HTML"
    )
    await callback.answer()

@dp.message(AdminStates.waiting_for_url)
async def process_open_url(message: types.Message, state: FSMContext):
    if not is_authorized(message):
        return
    data = await state.get_data()
    pc_name = data.get("target_pc")
    await state.clear()

    url = message.text.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        url = "https://" + url

    msg = await message.answer(f"⏳ Відкриваю {url} на {pc_name}...")
    resp = await manager.send_command(pc_name, "open_url", {"url": url}, timeout=6.0)

    if resp.get("status") == "ok":
        await msg.edit_text(f"✅ Посилання успішно відкрито на <b>{pc_name}</b>: {url}", parse_mode="HTML")
    else:
        await msg.edit_text(f"❌ Помилка на {pc_name}: {resp.get('message')}")

@dp.callback_query(F.data.startswith("act:kill_proc:"))
async def cb_kill_proc_prompt(callback: types.CallbackQuery, state: FSMContext):
    if not is_authorized(callback):
        return
    pc_name = callback.data.split(":")[2]
    await state.set_state(AdminStates.waiting_for_process_name)
    await state.update_data(target_pc=pc_name)
    await callback.message.answer(
        f"❌ Введіть назву процесу для закриття на <b>{pc_name}</b> (або <code>/kill {pc_name} назва</code>):",
        parse_mode="HTML"
    )
    await callback.answer()

@dp.message(AdminStates.waiting_for_process_name)
async def process_kill_proc(message: types.Message, state: FSMContext):
    if not is_authorized(message):
        return
    data = await state.get_data()
    pc_name = data.get("target_pc")
    await state.clear()

    proc_name = message.text.strip()
    msg = await message.answer(f"⏳ Закриваю процес <code>{proc_name}</code> на {pc_name}...", parse_mode="HTML")
    resp = await manager.send_command(pc_name, "kill_process", {"name": proc_name}, timeout=6.0)

    if resp.get("status") == "ok":
        killed_count = resp.get("killed_count", 1)
        await msg.edit_text(f"✅ Успішно завершено процесів (<code>{proc_name}</code>): <b>{killed_count}</b>", parse_mode="HTML")
    else:
        await msg.edit_text(f"❌ {resp.get('message')}")

@dp.callback_query(F.data.startswith("act:restart_confirm:"))
async def cb_restart_confirm(callback: types.CallbackQuery):
    if not is_authorized(callback):
        return
    pc_name = callback.data.split(":")[2]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Так, перезавантажити", callback_data=f"act:do_restart:{pc_name}"),
            InlineKeyboardButton(text="❌ Скасувати", callback_data=f"pc:{pc_name}")
        ]
    ])
    await callback.message.edit_text(f"⚠️ Ви впевнені, що хочете <b>перезавантажити {pc_name}</b>?", parse_mode="HTML", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("act:do_restart:"))
async def cb_do_restart(callback: types.CallbackQuery):
    if not is_authorized(callback):
        return
    pc_name = callback.data.split(":")[2]
    await callback.answer("Надсилаю команду перезавантаження...")
    resp = await manager.send_command(pc_name, "restart", timeout=6.0)
    if resp.get("status") == "ok":
        await callback.message.edit_text(f"🔄 Команда перезавантаження надіслана на <b>{pc_name}</b>.", parse_mode="HTML")
    else:
        await callback.message.edit_text(f"❌ Помилка: {resp.get('message')}")

@dp.callback_query(F.data.startswith("act:shutdown_confirm:"))
async def cb_shutdown_confirm(callback: types.CallbackQuery):
    if not is_authorized(callback):
        return
    pc_name = callback.data.split(":")[2]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚠️ Так, вимкнути", callback_data=f"act:do_shutdown:{pc_name}"),
            InlineKeyboardButton(text="❌ Скасувати", callback_data=f"pc:{pc_name}")
        ]
    ])
    await callback.message.edit_text(f"⚠️ Ви дійсно бажаєте <b>повністю вимкнути {pc_name}</b>?", parse_mode="HTML", reply_markup=kb)
    await callback.answer()

# --- Показ картинки на весь екран (/pic PC-01 url sec або фото з підписом) ---
@dp.message(Command("pic"))
async def cmd_quick_pic(message: types.Message, command: CommandObject):
    if not is_authorized(message):
        return
    args = (command.args or "").strip().split(maxsplit=2)
    if len(args) < 2:
        await message.reply("⚠️ Формат: <code>/pic PC-01 https://посилання.jpg 10</code>\n(або <code>/pic ALL https://... 10</code> для всіх ПК)", parse_mode="HTML")
        return

    target = args[0]
    img_url = args[1]
    duration = float(args[2]) if len(args) > 2 and args[2].isdigit() else 10.0

    msg = await message.reply(f"⏳ Відправляю картинку на <b>{target}</b> ({duration}с)...", parse_mode="HTML")
    params = {"image_url": img_url, "duration": duration}

    if target.upper() == "ALL":
        resp = await manager.send_broadcast_command("show_image", params)
        await msg.edit_text(f"🖼 Картинку надіслано на <b>ВСІ ПК</b> ({resp.get('count', 0)} комп'ютерів) на {duration} сек.", parse_mode="HTML")
    else:
        resp = await manager.send_command(target, "show_image", params, timeout=10.0)
        if resp.get("status") == "ok":
            await msg.edit_text(f"✅ Картинку відкрито на <b>{target}</b> на {duration} сек.", parse_mode="HTML")
        else:
            await msg.edit_text(f"❌ Помилка: {resp.get('message')}")

@dp.message(F.photo)
async def handle_photo_with_caption(message: types.Message):
    if not is_authorized(message):
        return
    caption = (message.caption or "").strip()
    if not caption.startswith("/pic"):
        return

    parts = caption.split()
    target = parts[1] if len(parts) > 1 else "ALL"
    duration = float(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 10.0

    msg = await message.reply(f"⏳ Завантажую фото та надсилаю на <b>{target}</b>...", parse_mode="HTML")
    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    photo_bytes_io = io.BytesIO()
    await message.bot.download_file(file.file_path, destination=photo_bytes_io)
    b64_img = base64.b64encode(photo_bytes_io.getvalue()).decode("utf-8")

    params = {"image_base64": b64_img, "duration": duration}
    if target.upper() == "ALL":
        resp = await manager.send_broadcast_command("show_image", params)
        await msg.edit_text(f"🖼 Фото виведено на весь екран на <b>ВСІ ПК</b> ({resp.get('count', 0)} комп'ютерів) на {duration} сек.", parse_mode="HTML")
    else:
        resp = await manager.send_command(target, "show_image", params, timeout=10.0)
        if resp.get("status") == "ok":
            await msg.edit_text(f"✅ Фото відкрито на <b>{target}</b> на {duration} сек.", parse_mode="HTML")
        else:
            await msg.edit_text(f"❌ Помилка: {resp.get('message')}")

# --- Масові команди (/shutdown_all, /restart_all) ---
@dp.message(Command("shutdown_all"))
async def cmd_shutdown_all(message: types.Message):
    if not is_authorized(message):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚠️ ТАК, ВИМКНУТИ ВСІ ПК", callback_data="mass:do_shutdown"),
            InlineKeyboardButton(text="❌ Скасувати", callback_data="back_to_list")
        ]
    ])
    await message.answer("⚠️ <b>УВАГА!</b> Ви дійсно бажаєте вимкнути <b>ВСІ комп'ютери клубу</b>?", parse_mode="HTML", reply_markup=kb)

@dp.message(Command("restart_all"))
async def cmd_restart_all(message: types.Message):
    if not is_authorized(message):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 ТАК, ПЕРЕЗАВАНТАЖИТИ ВСІ", callback_data="mass:do_restart"),
            InlineKeyboardButton(text="❌ Скасувати", callback_data="back_to_list")
        ]
    ])
    await message.answer("⚠️ <b>УВАГА!</b> Перезавантажити <b>ВСІ комп'ютери клубу</b>?", parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "mass:shutdown_confirm")
async def cb_mass_shutdown_confirm(callback: types.CallbackQuery):
    if not is_authorized(callback): return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚠️ ТАК, ВИМКНУТИ ВСІ ПК", callback_data="mass:do_shutdown"),
            InlineKeyboardButton(text="❌ Скасувати", callback_data="back_to_list")
        ]
    ])
    await callback.message.edit_text("⚠️ <b>УВАГА!</b> Ви дійсно бажаєте вимкнути <b>ВСІ комп'ютери клубу</b>?", parse_mode="HTML", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "mass:do_shutdown")
async def cb_mass_do_shutdown(callback: types.CallbackQuery):
    if not is_authorized(callback): return
    await callback.answer("Вимикаю всі ПК...")
    resp = await manager.send_broadcast_command("shutdown")
    await callback.message.edit_text(f"⏻ Команду вимкнення надіслано на <b>{resp.get('count', 0)} комп'ютерів</b>.", parse_mode="HTML")

@dp.callback_query(F.data == "mass:restart_confirm")
async def cb_mass_restart_confirm(callback: types.CallbackQuery):
    if not is_authorized(callback): return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 ТАК, ПЕРЕЗАВАНТАЖИТИ ВСІ", callback_data="mass:do_restart"),
            InlineKeyboardButton(text="❌ Скасувати", callback_data="back_to_list")
        ]
    ])
    await callback.message.edit_text("⚠️ <b>УВАГА!</b> Перезавантажити <b>ВСІ комп'ютери клубу</b>?", parse_mode="HTML", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "mass:do_restart")
async def cb_mass_do_restart(callback: types.CallbackQuery):
    if not is_authorized(callback): return
    await callback.answer("Перезавантажую всі ПК...")
    resp = await manager.send_broadcast_command("restart")
    await callback.message.edit_text(f"🔄 Команду перезавантаження надіслано на <b>{resp.get('count', 0)} комп'ютерів</b>.", parse_mode="HTML")

def get_bot_instance() -> Optional[Bot]:
    global bot
    if config.BOT_TOKEN and bot is None:
        bot = Bot(token=config.BOT_TOKEN)
    return bot

async def notify_pc_status(pc_name: str, event: str):
    """
    Надсилає сповіщення в дозволені чати/групи, коли ПК запускається або вимикається.
    event: 'online' | 'offline'
    """
    bot_inst = get_bot_instance()
    if not bot_inst:
        return

    target_chats = set(config.ALLOWED_CHAT_IDS + config.ADMIN_IDS)
    if not target_chats:
        return

    if event == "online":
        icon = "🟢"
        title = "Комп'ютер запущено / онлайн"
    else:
        icon = "🔴"
        title = "Комп'ютер відключено / офлайн"

    text = f"{icon} <b>[{pc_name}] {title}</b>"

    for chat_id in target_chats:
        try:
            await bot_inst.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Не вдалося надіслати сповіщення в чат {chat_id}: {e}")
