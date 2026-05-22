import asyncio
import os
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from curl_cffi.requests import AsyncSession
from dotenv import load_dotenv

load_dotenv()
dp = Dispatcher()

BOT_TOKEN = os.getenv("BOT_TOKEN")

user_history = {}
user_favorites = {}


class SearchState(StatesGroup):
    profession = State()
    country = State()
    min_salary = State()

async def fetch_freelance_projects(query: str, country: str, offset: int = 0) -> list:
    url = "https://www.freelancer.com/api/projects/0.1/projects/active/"
    clean_country = country.lower().strip()

    params = {
        "query": query,
        "limit": 5,
        "offset": offset
    }

    if clean_country not in ["все", "всё", "all", "-"]:
        params["countries[]"] = clean_country

    try:
        async with AsyncSession(impersonate="chrome") as session:
            response = await session.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                return data.get("result", {}).get("projects", [])
            return []
    except Exception as e:
        print(f"Ошибка API {e}")
        return []

async def display_projects(message: Message, projects: list, min_salary: float, current_offset: int, query: str, country: str):
    filtered_count = 0

    for project in projects:
        min_budget = float(project.get("budget", {}).get("minimum", 0) or 0)
        max_budget = float(project.get("budget", {}).get("maximum", 0) or 0)

        if min_budget < min_salary:
            continue

        filtered_count += 1
        title = project.get("title", "Без названия")
        owner_id = project.get("owner_id", "Не указан")
        company = f"Компания {owner_id}"
        currency = project.get("currency", {}).get("code", "USD")
        salary = f"{min_budget} - {max_budget} {currency}"

        seo_url = project.get("seo_url", "")
        link = f"https://www.freelancer.com/projects/{seo_url}" if seo_url else "https://www.freelancer.com"

        response_text = (
            f"<b>Название:</b> {title}\n"
            f" <b>Компания:</b> {company}\n"
            f"<b>Зарплата:</b> {salary}\n"
            f"<b>Ссылка:</b> {link}\n"
        )

        fav_callback = f"fav_{project.get('id', 0)}"
        user_favorites[f"tmp_{project.get('id')}"] = {"title": title, "link": link}

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⭐️ Добавить в избранное", callback_data=fav_callback)]
        ])

        await message.answer(response_text, parse_mode="HTML", reply_markup=keyboard, disable_web_page_preview=True)

    if filtered_count == 0:
        await message.answer("Вакансий, подходящих под ваш фильтр зарплаты, не найдено на этой странице.")

    next_offset = current_offset + 5
    more_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➡️ Ещё вакансии",
                              callback_data=f"more_{next_offset}_{query}_{country}_{min_salary}")]
    ])
    await message.answer("Хотите посмотреть больше результатов?", reply_markup=more_keyboard)


@dp.message(Command("start"))
async def main_start(message: Message):
    await message.answer(
        f"Привет, {message.from_user.first_name}!\nЯ продвинутый бот для поиска проектов на Freelance.com.\n\nДоступные команды:\n/search — поиск вакансий\n/last — повторить последний поиск\n/favorites — посмотреть избранное"
    )


@dp.message(Command("search"))
async def search_start(message: Message, state: FSMContext):
    await message.answer("Какая профессия вас интересует? (например: Developer)")
    await state.set_state(SearchState.profession)


@dp.message(SearchState.profession)
async def process_profession(message: Message, state: FSMContext):
    await state.update_data(profession=message.text)
    await message.answer("Введите двухбуквенный код страны (например: us) или напишите 'все':")
    await state.set_state(SearchState.country)

@dp.message(SearchState.country)
async def process_country(message: Message, state: FSMContext):
    await state.update_data(country=message.text)
    await message.answer("Введите минимальную зарплату в USD (или 0, если без фильтра):")
    await state.set_state(SearchState.min_salary)


@dp.message(SearchState.min_salary)
async def process_min_salary(message: Message, state: FSMContext):
    try:
        min_salary = float(message.text)
    except ValueError:
        await message.answer("Некорректный вводб введите число. Поиск запущен со значением 0")
        min_salary = 0.0

    user_data = await state.get_data()
    profession = user_data['profession']
    country = user_data['country']
    user_id = message.from_user.id

    user_history[user_id] = {"query": profession, "country": country, "min_salary": min_salary}

    await message.answer("Ищу подходящие объявления, подождите...")
    projects = await fetch_freelance_projects(profession, country, offset=0)

    if not projects:
        await message.answer("Вакансий по вашему запросу не найдено.")
        await state.clear()
        return

    await display_projects(message, projects, min_salary, current_offset=0, query=profession, country=country)
    await state.clear()


@dp.message(Command("last"))
async def main_last(message: Message):
    user_id = message.from_user.id
    history = user_history.get(user_id)

    if not history:
        return await message.answer("Вы еще ничего не искали, используйте команду /search.")

    await message.answer(f"Повторяю поиск: {history['query']} ({history['country']}) от {history['min_salary']}$")
    projects = await fetch_freelance_projects(history['query'], history['country'], offset=0)

    if not projects:
        return await message.answer("Вакансий по вашему запросу не найдено")

    await display_projects(message, projects, history['min_salary'], current_offset=0, query=history['query'], country=history['country'])


@dp.message(Command("favorites"))
async def main_favorites(message: Message):
    user_id = message.from_user.id
    favs = user_favorites.get(user_id, [])

    if not favs:
        return await message.answer("Ваш список избранного пуст. Добавляйте вакансии кнопкой под ними")

    res = "⭐️ <b>Ваши избранные вакансии:</b>\n\n"
    for idx, item in enumerate(favs, 1):
        res += f"{idx}. <a href='{item['link']}'>{item['title']}</a>\n\n"

    await message.answer(res, parse_mode="HTML", disable_web_page_preview=True)


@dp.callback_query()
async def handle_callbacks(callback: CallbackQuery):
    user_id = callback.from_user.id
    data = callback.data

    if data.startswith("more_"):
        _, offset, query, country, min_salary = data.split("_", 4)
        offset = int(offset)
        min_salary = float(min_salary)

        await callback.message.answer(f"Загружаю следующую страницу (Проекты {offset + 1}-{offset + 5})...")
        projects = await fetch_freelance_projects(query, country, offset=offset)

        if not projects:
            await callback.message.answer("Это были все доступные вакансии по вашему запросу.")
            return await callback.answer()

        await display_projects(callback.message, projects, min_salary, current_offset=offset, query=query,
                               country=country)
        await callback.answer()

    elif data.startswith("fav_"):
        project_id = data.split("_")[1]
        cached_project = user_favorites.get(f"tmp_{project_id}")

        if cached_project:
            if user_id not in user_favorites:
                user_favorites[user_id] = []

            if cached_project not in user_favorites[user_id]:
                user_favorites[user_id].append(cached_project)
                await callback.answer("✅ Добавлено в избранное!", show_alert=True)
            else:
                await callback.answer("ℹ️ Эта вакансия уже есть в вашем избранном.", show_alert=True)
        else:
            await callback.answer("Ошибка: сессия устарела. Попробуйте выполнить поиск заново.", show_alert=True)


async def main():
    bot = Bot(token=BOT_TOKEN)
    print("Бот для Freelance.com запущен")
    await dp.start_polling(bot)


asyncio.run(main())
