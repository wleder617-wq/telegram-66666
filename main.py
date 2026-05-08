import telebot
from telebot import types
import sqlite3
import os
import time
from flask import Flask
from threading import Thread

from premium_emojis import get_emoji_tag
from i18n import get_string

E_HAND = get_emoji_tag('WAVE', '👋')
E_HEART = get_emoji_tag('HEART_RED', '❤️')
E_STAR = get_emoji_tag('STAR_GOLD', '⭐')
E_WOW = get_emoji_tag('WOW_FACE', '😮')
E_FIRE = get_emoji_tag('FIRE', '🔥')
E_GIFT = get_emoji_tag('GIFT', '🎁')
E_CHECK = get_emoji_tag('CHECK_MARK', '✅')
E_CHECK_ALT = get_emoji_tag('CHECK_MARK_ALT', '✔️')
E_PLANE = get_emoji_tag('PLANE', '✈️')
E_WINK = get_emoji_tag('WINK', '😉')
E_KISS = get_emoji_tag('KISS', '😘')
E_PLEASE = get_emoji_tag('PLEADING_FACE', '🥺')
E_SPARKLES = get_emoji_tag('STAR_GOLD', '✨')

TOKEN = "8721285488:AAGym7ilHiXEBHQ-gkjIsTtNzfdZFwSZsrw"
DATABASE = 'payments.db'
PROVIDER_TOKEN = '187703658:TEST:5d5b04968f5d1a03e9fc853d6895cf8f8f5254fb'
ADMIN_IDS = [7972155518]
NOTIFY_IDS = [7972155518]

REFERRAL_TIERS = [
    (2, 5, "Bronze"),
    (5, 12, "Silver"),
    (10, 25, "Gold"),
    (25, 62, "Platinum"),
    (50, 125, "Diamond"),
    (100, 250, "Legend"),
    (200, 500, "Ultimate"),
    (250, 750, "Supreme"),
]

def is_admin(user_id):
    return user_id in ADMIN_IDS

bot = telebot.TeleBot(TOKEN)
BOT_USERNAME = None
app = Flask(__name__)

def setup_bot_commands():
    commands = [
        types.BotCommand("start", "Start Bot"),
        types.BotCommand("offer", "Special Offers")
    ]
    try:
        bot.set_my_commands(commands)
    except Exception as e:
        print(f"Error setting commands: {e}")

setup_bot_commands()

@app.route('/')
def home():
    return "Bot is running!", 200

@app.route('/health')
def health():
    return "OK", 200

def run_flask():
    app.run(host='0.0.0.0', port=5000)

def init_db():
    print(f"DEBUG: Initializing database at {os.path.abspath(DATABASE)}")
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, language TEXT DEFAULT 'en', last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS payments (user_id INTEGER, payment_id TEXT, amount INTEGER, currency TEXT, PRIMARY KEY (user_id, payment_id))''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS videos (id INTEGER PRIMARY KEY AUTOINCREMENT, file_id TEXT NOT NULL, file_name TEXT, file_size INTEGER, duration INTEGER, added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS sent_videos (user_id INTEGER, video_id INTEGER, PRIMARY KEY (user_id, video_id))''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS referrals (referrer_id INTEGER, referred_id INTEGER, PRIMARY KEY (referred_id))''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS share_rewards (user_id INTEGER PRIMARY KEY, rewarded BOOLEAN DEFAULT FALSE)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS banned_users (user_id INTEGER PRIMARY KEY, banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS gift_claims (user_id INTEGER PRIMARY KEY, last_claim_time TIMESTAMP NOT NULL)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS daily_subscriptions (user_id INTEGER PRIMARY KEY, days_remaining INTEGER, last_sent_date TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS processed_deep_links (link_id TEXT PRIMARY KEY, used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS milestones (user_id INTEGER PRIMARY KEY, total_spent INTEGER DEFAULT 0, rewarded BOOLEAN DEFAULT FALSE)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS admin_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER, action TEXT, target_id INTEGER, details TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS referral_rewards (user_id INTEGER, tier_invites INTEGER, claimed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (user_id, tier_invites))''')
        cursor.execute('''CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)''')
        cursor.execute('''CREATE INDEX IF NOT EXISTS idx_sent_videos_user ON sent_videos(user_id)''')
        cursor.execute('''CREATE INDEX IF NOT EXISTS idx_videos_file_id ON videos(file_id)''')
        cursor.execute('''CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id)''')
        try:
            cursor.execute('ALTER TABLE users ADD COLUMN language TEXT')
        except sqlite3.OperationalError:
            pass
        conn.commit()

def is_banned(user_id):
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM banned_users WHERE user_id = ?', (user_id,))
        return cursor.fetchone() is not None

def ban_user(user_id):
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO banned_users (user_id) VALUES (?)', (user_id,))
        conn.commit()

def unban_user(user_id):
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM banned_users WHERE user_id = ?', (user_id,))
        conn.commit()

def mark_link_used(link_id):
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT INTO processed_deep_links (link_id) VALUES (?)', (link_id,))
            conn.commit()
            return True
    except sqlite3.IntegrityError:
        return False

ADMIN_STATES = {}

def save_user(user_id, username):
    is_new = False
    with sqlite3.connect(DATABASE, isolation_level=None) as conn:
        cursor = conn.cursor()
        cursor.execute('BEGIN TRANSACTION')
        try:
            cursor.execute('SELECT 1 FROM users WHERE user_id = ?', (user_id,))
            if not cursor.fetchone():
                is_new = True
                cursor.execute('INSERT INTO users (user_id, username, last_seen) VALUES (?, ?, CURRENT_TIMESTAMP)', (user_id, username))
            else:
                cursor.execute('UPDATE users SET username = ?, last_seen = CURRENT_TIMESTAMP WHERE user_id = ?', (username, user_id))
            cursor.execute('COMMIT')
        except Exception as e:
            cursor.execute('ROLLBACK')
            print(f"Error saving user: {e}")
    if is_new:
        for admin_id in NOTIFY_IDS:
            try:
                bot.send_message(admin_id,
                    f"{E_HEART} <b>New Member Joined!</b>\n\n"
                    f"👤 <b>User:</b> @{escape_html(username) if username else 'N/A'}\n"
                    f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
                    f"✨ <b>Welcome them to the club!</b>",
                    parse_mode='HTML')
            except: pass

def escape_html(text):
    if not text: return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def add_referral(referrer_id, referred_id):
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM referrals WHERE referred_id = ?', (referred_id,))
        if cursor.fetchone(): return False
        cursor.execute('INSERT OR IGNORE INTO referrals (referrer_id, referred_id) VALUES (?, ?)', (referrer_id, referred_id))
        conn.commit()
        return True

def get_referral_count(referrer_id):
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM referrals WHERE referrer_id = ?', (referrer_id,))
        return cursor.fetchone()[0]

def get_claimed_tiers(user_id):
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT tier_invites FROM referral_rewards WHERE user_id = ?', (user_id,))
        return [row[0] for row in cursor.fetchall()]

def claim_tier(user_id, tier_invites):
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT INTO referral_rewards (user_id, tier_invites) VALUES (?, ?)', (user_id, tier_invites))
            conn.commit()
            return True
    except sqlite3.IntegrityError:
        return False

def get_next_tier(ref_count, claimed_tiers):
    for invites_needed, reward, name in REFERRAL_TIERS:
        if invites_needed not in claimed_tiers:
            return (invites_needed, reward, name)
    return None

def get_referral_leaderboard(limit=10):
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT r.referrer_id, u.username, COUNT(*) as ref_count
            FROM referrals r
            LEFT JOIN users u ON r.referrer_id = u.user_id
            GROUP BY r.referrer_id
            ORDER BY ref_count DESC
            LIMIT ?
        ''', (limit,))
        return cursor.fetchall()

def save_video(file_id, file_name=None, file_size=None, duration=None):
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM videos WHERE file_id = ?', (file_id,))
            exists = cursor.fetchone()
            if exists:
                return exists[0]
            cursor.execute('INSERT INTO videos (file_id, file_name, file_size, duration) VALUES (?, ?, ?, ?)', (file_id, file_name, file_size, duration))
            conn.commit()
            return cursor.lastrowid
    except Exception as e:
        print(f"DB error save_video: {e}")
        return None

def get_unsent_videos(user_id, limit=50):
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT OR IGNORE INTO users (user_id) VALUES (?)', (user_id,))

            query_unsent = '''
                SELECT v.id, v.file_id 
                FROM videos v 
                LEFT JOIN sent_videos sv ON v.id = sv.video_id AND sv.user_id = ? 
                WHERE sv.video_id IS NULL 
                ORDER BY RANDOM() 
                LIMIT ?
            '''
            cursor.execute(query_unsent, (user_id, limit))
            videos = cursor.fetchall()

            if len(videos) < limit:
                needed = limit - len(videos)
                exclude_ids = [v[0] for v in videos]
                placeholders = ','.join(['?'] * len(exclude_ids))

                query_recycle = f'''
                    SELECT id, file_id 
                    FROM videos 
                    {f"WHERE id NOT IN ({placeholders})" if exclude_ids else ""}
                    ORDER BY RANDOM() 
                    LIMIT ?
                '''
                params = exclude_ids + [needed]
                cursor.execute(query_recycle, params)
                videos.extend(cursor.fetchall())

            return videos[:limit]
    except Exception as e:
        print(f"DB error get_unsent_videos: {e}")
        return []

def save_sent_video(user_id, video_id):
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT OR IGNORE INTO sent_videos (user_id, video_id) VALUES (?, ?)', (user_id, video_id))
            conn.commit()
    except Exception as e:
        print(f"DB error save_sent_video: {e}")

import queue
import threading
from concurrent.futures import ThreadPoolExecutor

delivery_queue = queue.Queue()
delivery_pool = ThreadPoolExecutor(max_workers=10)

def process_delivery(task):
    try:
        if len(task) == 5:
            user_id, video_list, success_callback, failure_callback, admin_msg_id = task
        else:
            user_id, video_list, success_callback, failure_callback = task
            admin_msg_id = None

        total_vids = len(video_list)
        CAPTION = ""
        success_count = 0

        for idx, (v_id, f_id) in enumerate(video_list):
            try:
                time.sleep(0.3)
                bot.send_video(user_id, f_id, caption=CAPTION)
                save_sent_video(user_id, v_id)
                success_count += 1

                if admin_msg_id and (success_count % 5 == 0 or success_count == total_vids):
                    for admin_id in NOTIFY_IDS:
                        try:
                            bot.edit_message_text(
                                f"🚀 <b>Delivery Progress</b>\n"
                                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"User ID: <code>{user_id}</code>\n"
                                f"Progress: <b>{success_count}/{total_vids}</b> videos\n"
                                f"Status: <b>Sending...</b>",
                                admin_id, admin_msg_id, parse_mode='HTML'
                            )
                        except: pass
            except Exception as e:
                print(f"Worker error: {e}")
                if "blocked" in str(e).lower(): break

        if admin_msg_id:
            for admin_id in NOTIFY_IDS:
                try:
                    bot.edit_message_text(
                        f"✅ <b>Delivery Complete</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"User ID: <code>{user_id}</code>\n"
                        f"Total: <b>{success_count}/{total_vids}</b> videos sent.",
                        admin_id, admin_msg_id, parse_mode='HTML'
                    )
                except: pass

        if success_count > 0:
            if success_callback: success_callback(user_id, success_count)
        else:
            if failure_callback: failure_callback(user_id)
    except Exception as e:
        print(f"Delivery worker error: {e}")

def delivery_dispatcher():
    while True:
        try:
            task = delivery_queue.get()
            delivery_pool.submit(process_delivery, task)
            delivery_queue.task_done()
        except Exception as e:
            print(f"Dispatcher error: {e}")

threading.Thread(target=delivery_dispatcher, daemon=True).start()

def get_user_language(user_id):
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT language FROM users WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        return row[0] if row and row[0] else 'en'

def set_user_language(user_id, lang):
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET language = ? WHERE user_id = ?', (lang, user_id))
        conn.commit()

def language_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("English 🇺🇸", callback_data="set_lang_en"),
        types.InlineKeyboardButton("Русский 🇷🇺", callback_data="set_lang_ru"),
        types.InlineKeyboardButton("हिन्दी 🇮🇳", callback_data="set_lang_hi"),
        types.InlineKeyboardButton("Español 🇪🇸", callback_data="set_lang_es"),
        types.InlineKeyboardButton("Deutsch 🇩🇪", callback_data="set_lang_de"),
        types.InlineKeyboardButton("Português 🇵🇹", callback_data="set_lang_pt")
    )
    return keyboard

@bot.callback_query_handler(func=lambda call: call.data.startswith("set_lang_"))
def handle_set_lang(call):
    lang = call.data.replace("set_lang_", "")
    set_user_language(call.from_user.id, lang)
    bot.answer_callback_query(call.id, f"Language set to {lang}!")
    handle_back_to_start(call)

@bot.callback_query_handler(func=lambda call: call.data == "change_lang")
def handle_change_lang(call):
    lang = get_user_language(call.from_user.id)
    bot.edit_message_text(
        get_string('select_language', lang),
        call.message.chat.id,
        call.message.message_id,
        reply_markup=language_keyboard()
    )

def notify_delivery_success(user_id, count):
    lang = get_user_language(user_id)
    try:
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(styled_button(get_string('referral_menu', lang), callback_data="referral_menu", style="success"))
        keyboard.add(styled_button(get_string('back_to_start', lang), callback_data="back_to_start", style="primary"))
        bot.send_message(user_id, get_string('delivery_success', lang, count=count), parse_mode='HTML', reply_markup=keyboard)
    except: pass

def notify_delivery_failure(user_id):
    lang = get_user_language(user_id)
    try: bot.send_message(user_id, get_string('delivery_failed', lang, user_id=user_id), parse_mode='HTML')
    except: pass

def get_total_users():
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM users')
            return cursor.fetchone()[0]
    except:
        return 0

def styled_button(text, callback_data=None, url=None, style="primary", emoji_id=None):
    btn = types.InlineKeyboardButton(text=text, callback_data=callback_data, url=url)
    original_to_dict = btn.to_dict
    def to_dict():
        data = original_to_dict()
        data['style'] = style
        if emoji_id:
            data['icon_custom_emoji_id'] = emoji_id
        return data
    btn.to_dict = to_dict
    return btn

def get_user_milestone(user_id):
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT total_spent, rewarded FROM milestones WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        if row: return row
        return (0, False)

def update_user_milestone(user_id, amount):
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO milestones (user_id, total_spent) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET total_spent = total_spent + EXCLUDED.total_spent
        ''', (user_id, amount))
        conn.commit()
        cursor.execute('SELECT total_spent, rewarded FROM milestones WHERE user_id = ?', (user_id,))
        total, rewarded = cursor.fetchone()
        if total >= 750 and not rewarded:
            cursor.execute('UPDATE milestones SET rewarded = TRUE WHERE user_id = ?', (user_id,))
            conn.commit()
            return True
    return False

def log_admin_action(admin_id, action, target_id=None, details=None):
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT INTO admin_logs (admin_id, action, target_id, details) VALUES (?, ?, ?, ?)',
                         (admin_id, action, target_id, details))
            conn.commit()
    except Exception as e:
        print(f"Error logging admin action: {e}")

def build_referral_progress(ref_count, claimed_tiers):
    lines = []
    for invites_needed, reward, name in REFERRAL_TIERS:
        if invites_needed in claimed_tiers:
            lines.append(f"✅ <b>{name}</b> — <i>Claimed</i>")
        elif ref_count >= invites_needed:
            lines.append(f"🎁 <b>{name}</b> — <b>READY!</b>")
        else:
            percent = min(100, int((ref_count / invites_needed) * 100))
            bar = "▰" * (percent // 10) + "▱" * (10 - (percent // 10))
            lines.append(f"🔒 <b>{name}</b> ({ref_count}/{invites_needed})\n└ {bar} {percent}%")
    return "\n".join(lines)

def start_keyboard(user_id=None):
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    lang = get_user_language(user_id) if user_id else 'en'
    from premium_emojis import PREMIUM_EMOJIS
    star_emoji_id = PREMIUM_EMOJIS.get('STAR_GOLD')
    fire_emoji_id = PREMIUM_EMOJIS.get('FIRE')
    gift_emoji_id = PREMIUM_EMOJIS.get('GIFT')
    wave_emoji_id = PREMIUM_EMOJIS.get('WAVE')
    heart_emoji_id = PREMIUM_EMOJIS.get('HEART_RED')

    keyboard.add(types.InlineKeyboardButton(text="Join Group 🚀", url="https://t.me/+ARG5VlNBj4NhYWE0"))
    keyboard.add(styled_button(text="175,000 Videos 💎 5000 Stars", callback_data="buy_175000", style="success", emoji_id=star_emoji_id))
    keyboard.add(
        styled_button(text=get_string('buy_50', lang), callback_data="buy_50", style="primary", emoji_id=star_emoji_id),
        styled_button(text=get_string('buy_5', lang), callback_data="buy_5", style="primary", emoji_id=star_emoji_id)
    )

    if user_id:
        ref_count = get_referral_count(user_id)
        claimed_tiers = get_claimed_tiers(user_id)
        next_tier = get_next_tier(ref_count, claimed_tiers)

        global BOT_USERNAME
        if not BOT_USERNAME:
            try:
                me = bot.get_me()
                BOT_USERNAME = me.username
            except:
                BOT_USERNAME = "bot"
        
        invite_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
        share_text = f"Hey! I found an amazing Video Bot! 🎬\n\nGet videos just by joining!\nInvite friends & unlock videos!\nContent delivered instantly!\n\nJoin now\n{invite_link}"
        import urllib.parse
        share_url = f"https://t.me/share/url?url={urllib.parse.quote(invite_link)}&text={urllib.parse.quote(share_text)}"
        
        has_claimable = any(ref_count >= inv and inv not in claimed_tiers for inv, _, _ in REFERRAL_TIERS)
        
        if has_claimable:
            keyboard.add(styled_button(text=get_string('claim_rewards', lang), callback_data="claim_rewards", style="danger", emoji_id=gift_emoji_id))
        
        if next_tier:
            invites_needed, reward, name = next_tier
            keyboard.add(styled_button(text=f"{get_string('invite_friends', lang)} ({ref_count}/{invites_needed})", url=share_url, style="success", emoji_id=wave_emoji_id))
        else:
            keyboard.add(styled_button(text=f"{get_string('all_tiers_done', lang)} ({ref_count})", url=share_url, style="success", emoji_id=star_emoji_id))

        keyboard.add(styled_button(text=get_string('referral_menu', lang) + f" ({ref_count})", callback_data="referral_menu", style="primary", emoji_id=heart_emoji_id))

    keyboard.add(
        styled_button(text="Offers", callback_data="offer_menu", style="success", emoji_id=fire_emoji_id),
        styled_button(text=get_string('leaderboard', lang), callback_data="leaderboard", style="primary", emoji_id=star_emoji_id)
    )

    keyboard.add(types.InlineKeyboardButton("Language 🌐", callback_data="change_lang"))
    
    if user_id and is_admin(user_id):
        total_users = get_total_users()
        keyboard.add(styled_button(text=f"Admin Panel ({total_users})", callback_data="none", style="primary"))

    return keyboard

@bot.callback_query_handler(func=lambda call: call.data == "back_to_start")
def handle_back_to_start(call):
    lang = get_user_language(call.from_user.id)
    welcome_text = get_string('welcome', lang)
    try:
        bot.edit_message_text(
            welcome_text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=start_keyboard(call.from_user.id),
            parse_mode='HTML'
        )
    except:
        try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=start_keyboard(call.from_user.id))
        except: pass

@bot.message_handler(commands=['dee'])
def handle_dee_command(message):
    lang = get_user_language(message.from_user.id)
    from premium_emojis import PREMIUM_EMOJIS
    fire_emoji = PREMIUM_EMOJIS.get('FIRE')
    star_emoji = PREMIUM_EMOJIS.get('STAR_GOLD')
    gift_emoji = PREMIUM_EMOJIS.get('GIFT')

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(
        text=f"BUY NOW {star_emoji}",
        callback_data="buy_499_special"
    ))

    offer_text = (
        f"{fire_emoji} <b>EXCLUSIVE LIMITED OFFER!</b> {fire_emoji}\n\n"
        f"Unlock <b>499 Premium Videos</b> {gift_emoji}\n"
        f"For only <b>399 Stars</b> {star_emoji}\n\n"
        f"⚡ <i>Instant Delivery guaranteed!</i>"
    )

    bot.send_message(message.chat.id, offer_text, parse_mode='HTML', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "buy_499_special")
def handle_buy_499(call):
    user_id = call.from_user.id
    prices = [types.LabeledPrice(label='499 Premium Videos', amount=399)]
    
    bot.send_invoice(
        call.message.chat.id,
        title="Special Offer: 499 Videos",
        description="Get 499 high-quality premium videos instantly!",
        invoice_payload="deliver_videos_499",
        provider_token=PROVIDER_TOKEN,
        currency="XTR",
        prices=prices,
        start_parameter="special_offer_499"
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "offer_menu")
def handle_offer_menu(call):
    user_id = call.from_user.id
    lang = get_user_language(user_id)
    from premium_emojis import PREMIUM_EMOJIS
    star_id = PREMIUM_EMOJIS.get('STAR_GOLD')

    keyboard = types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        styled_button("⭐ 100 Stars ➔ 120 Videos", callback_data="buy_120", emoji_id=star_id),
        styled_button("⭐ 250 Stars ➔ 350 Videos", callback_data="buy_350", emoji_id=star_id),
        styled_button("⭐ 500 Stars ➔ 750 Videos", callback_data="buy_750", emoji_id=star_id),
        styled_button("⭐ 1000 Stars ➔ 1600 Videos", callback_data="buy_1600", emoji_id=star_id),
        styled_button(get_string('back_to_start', lang), callback_data="back_to_start", style="primary")
    )

    bot.edit_message_text(
        "✨ <b>Special Premium Offers</b> ✨\n\nChoose your pack and get instant delivery!",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard,
        parse_mode='HTML'
    )

@bot.message_handler(commands=['offer'])
def handle_offer_command(message):
    user_id = message.from_user.id
    lang = get_user_language(user_id)
    from premium_emojis import PREMIUM_EMOJIS
    star_id = PREMIUM_EMOJIS.get('STAR_GOLD')

    keyboard = types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        styled_button("⭐ 100 Stars ➔ 120 Videos", callback_data="buy_120", emoji_id=star_id),
        styled_button("⭐ 250 Stars ➔ 350 Videos", callback_data="buy_350", emoji_id=star_id),
        styled_button("⭐ 500 Stars ➔ 750 Videos", callback_data="buy_750", emoji_id=star_id),
        styled_button("⭐ 1000 Stars ➔ 1600 Videos", callback_data="buy_1600", emoji_id=star_id),
        styled_button(get_string('back_to_start', lang), callback_data="back_to_start", style="primary")
    )

    bot.send_message(
        message.chat.id,
        "✨ <b>Special Premium Offers</b> ✨\n\nChoose your pack and get instant delivery!",
        reply_markup=keyboard,
        parse_mode='HTML'
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_"))
def handle_payment_request(call):
    user_id = call.from_user.id
    try:
        count = int(call.data.replace("buy_", ""))
    except ValueError:
        return

    stars_map = {
        7: 7,
        65: 65,
        120: 100,
        350: 250,
        750: 500,
        1600: 1000,
        175000: 5000
    }

    stars_price = stars_map.get(count, count)

    prices = [types.LabeledPrice(label=f"{count} Videos", amount=stars_price)]
    bot.send_invoice(
        call.message.chat.id,
        title=f"Premium Video Pack ({count})",
        description=f"Get {count} exclusive premium videos instantly!",
        invoice_payload=f"deliver_{user_id}_{count}",
        provider_token="",
        currency="XTR",
        prices=prices,
        start_parameter="premium_videos"
    )

@bot.callback_query_handler(func=lambda call: call.data == "referral_menu")
def handle_referral_menu(call):
    user_id = call.from_user.id
    lang = get_user_language(user_id)
    ref_count = get_referral_count(user_id)
    claimed_tiers = get_claimed_tiers(user_id)

    global BOT_USERNAME
    if not BOT_USERNAME: BOT_USERNAME = bot.get_me().username
    invite_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
    share_text = f"🔥 Hey! I found an amazing Premium Video Bot! 🎬\n\n🎁 Get FREE videos just by joining!\n✨ Invite friends & unlock up to 750+ videos!\n⭐ Premium content delivered instantly!\n\n👇 Join now 👇\n{invite_link}"
    import urllib.parse
    share_url = f"https://t.me/share/url?url={urllib.parse.quote(invite_link)}&text={urllib.parse.quote(share_text)}"

    total_earned = sum(reward for inv, reward, _ in REFERRAL_TIERS if inv in claimed_tiers)
    progress_text = build_referral_progress(ref_count, claimed_tiers)

    text = (
        f"{get_string('dashboard_title', lang)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>{get_string('total_invites', lang)}:</b> <code>{ref_count}</code>\n"
        f"<b>{get_string('videos_earned', lang)}:</b> <code>{total_earned}</code>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{progress_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>{get_string('invite_link_label', lang)}:</b>\n<code>{invite_link}</code>\n\n"
        f"{get_string('invite_hint', lang)}"
    )

    keyboard = types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(styled_button(get_string('share_link', lang), url=share_url, style="success"))

    has_claimable = any(
        ref_count >= inv and inv not in claimed_tiers
        for inv, _, _ in REFERRAL_TIERS
    )
    if has_claimable:
        keyboard.add(styled_button(get_string('claim_rewards', lang), callback_data="claim_rewards", style="danger"))

    keyboard.add(styled_button(get_string('back_to_start', lang), callback_data="back_to_start", style="primary"))

    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=keyboard, parse_mode='HTML')
    except:
        try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=keyboard)
        except: pass

@bot.callback_query_handler(func=lambda call: call.data == "claim_rewards")
def handle_claim_rewards(call):
    user_id = call.from_user.id
    lang = get_user_language(user_id)
    ref_count = get_referral_count(user_id)
    claimed_tiers = get_claimed_tiers(user_id)

    total_videos_to_deliver = 0
    tiers_to_claim = []

    for invites_needed, reward, name in REFERRAL_TIERS:
        if ref_count >= invites_needed and invites_needed not in claimed_tiers:
            total_videos_to_deliver += reward
            tiers_to_claim.append((invites_needed, reward, name))

    if total_videos_to_deliver == 0:
        bot.answer_callback_query(call.id, get_string('no_rewards', lang), show_alert=True)
        return

    unsent = get_unsent_videos(user_id, limit=total_videos_to_deliver)
    if not unsent:
        bot.answer_callback_query(call.id, get_string('no_videos', lang), show_alert=True)
        return

    tiers_claimed_now = []
    for invites_needed, reward, name in tiers_to_claim:
        if claim_tier(user_id, invites_needed):
            tiers_claimed_now.append((name, reward))

    if not tiers_claimed_now:
        bot.answer_callback_query(call.id, "Rewards already claimed!", show_alert=True)
        return

    tier_text = "\n".join([f"✅ {name}: +{reward} videos" for name, reward in tiers_claimed_now])
    bot.answer_callback_query(call.id, get_string('delivering_now', lang, count=len(unsent)))

    bot.send_message(user_id,
        f"{get_string('rewards_claimed_title', lang)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{tier_text}\n\n"
        f"{get_string('total_incoming', lang, count=len(unsent))}",
        parse_mode='HTML')

    delivery_queue.put((user_id, unsent, notify_delivery_success, notify_delivery_failure, None))

    for admin_id in NOTIFY_IDS:
        try:
            bot.send_message(admin_id,
                f"🎁 <b>Referral Reward Claimed!</b>\n\n"
                f"👤 User: <code>{user_id}</code>\n"
                f"👥 Invites: {ref_count}\n"
                f"📦 Videos: {len(unsent)}\n"
                f"🏆 Tiers: {', '.join([n for n, _ in tiers_claimed_now])}",
                parse_mode='HTML')
        except: pass

@bot.callback_query_handler(func=lambda call: call.data == "leaderboard")
def handle_leaderboard(call):
    lang = get_user_language(call.from_user.id)
    leaders = get_referral_leaderboard(10)

    if not leaders:
        text = (
            f"{get_string('leaderboard_title', lang)}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{get_string('no_leaders', lang)}"
        )
    else:
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        lines = []
        for i, (uid, uname, count) in enumerate(leaders):
            medal = medals[i] if i < len(medals) else f"#{i+1}"
            display = f"@{uname}" if uname else f"ID:{uid}"
            lines.append(f"{medal} {display} — <b>{count}</b> invites")

        text = (
            f"{get_string('leaderboard_title', lang)}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            + "\n".join(lines) +
            f"\n\n{get_string('climb_ranks', lang)}"
        )

    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(styled_button(get_string('back_to_start', lang), callback_data="back_to_start", style="primary"))

    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=keyboard, parse_mode='HTML')
    except:
        try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=keyboard)
        except: pass

@bot.callback_query_handler(func=lambda call: call.data in ["buy_175000", "buy_50", "buy_5", "buy_120", "buy_350", "buy_750", "buy_1600"])
def handle_specific_buys(call):
    handle_payment_request(call)

@bot.callback_query_handler(func=lambda call: call.data == "none")
def handle_none(call):
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda message: is_banned(message.from_user.id))
def handle_banned(message):
    bot.send_message(message.chat.id, "🚫 You are banned from using this bot.")

@bot.message_handler(commands=['start'])
def handle_start(message):
    user_id = message.from_user.id
    username = message.from_user.username
    is_new = False

    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM users WHERE user_id = ?', (user_id,))
        if not cursor.fetchone(): 
            is_new = True
            save_user(user_id, username)
            bot.send_message(message.chat.id, "Please select your language / Пожалуйста, выберите язык:", reply_markup=language_keyboard())
            args = message.text.split()
            if len(args) > 1 and args[1].isdigit():
                referrer_id = int(args[1])
                if referrer_id != user_id:
                    add_referral(referrer_id, user_id)
            return

    save_user(user_id, username)
    lang = get_user_language(user_id)
    welcome_text = get_string('welcome', lang)
    bot.send_message(message.chat.id, welcome_text, parse_mode='HTML', reply_markup=start_keyboard(user_id))

@bot.message_handler(commands=['check'])
def handle_check_referral(message):
    user_id = message.from_user.id
    ref_count = get_referral_count(user_id)
    claimed_tiers = get_claimed_tiers(user_id)

    global BOT_USERNAME
    if not BOT_USERNAME: BOT_USERNAME = bot.get_me().username
    invite_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"

    progress_text = build_referral_progress(ref_count, claimed_tiers)
    total_earned = sum(reward for inv, reward, _ in REFERRAL_TIERS if inv in claimed_tiers)

    text = (
        f"🏆 <b>REFERRAL STATS</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 <b>Total Invites:</b> <code>{ref_count}</code>\n"
        f"🎁 <b>Videos Earned:</b> <code>{total_earned}</code>\n\n"
        f"{progress_text}\n\n"
        f"🔗 <b>Your Link:</b>\n<code>{invite_link}</code>"
    )
    bot.send_message(message.chat.id, text, parse_mode='HTML')

@bot.message_handler(commands=['logs'])
def handle_view_logs(message):
    if not is_admin(message.from_user.id): return
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT al.admin_id, u.username, al.action, al.target_id, al.timestamp 
                FROM admin_logs al
                LEFT JOIN users u ON al.admin_id = u.user_id
                ORDER BY al.timestamp DESC 
                LIMIT 20
            ''')
            logs = cursor.fetchall()

        if not logs:
            bot.reply_to(message, "No admin logs found.")
            return

        text = "📜 <b>Recent Admin Activity</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        for aid, uname, action, target, ts in logs:
            admin_display = f"@{uname}" if uname else f"ID:{aid}"
            target_display = f" (Target: {target})" if target else ""
            text += f"👤 {admin_display}\n└ <b>{action}</b>{target_display}\n🕒 <code>{ts}</code>\n\n"

        bot.send_message(message.chat.id, text, parse_mode='HTML')
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

@bot.message_handler(commands=['buyers'])
def handle_buyers_list(message):
    if not is_admin(message.from_user.id): return
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT u.user_id, u.username, m.total_spent 
            FROM users u
            JOIN milestones m ON u.user_id = m.user_id
            WHERE m.total_spent > 0
            ORDER BY m.total_spent DESC
            LIMIT 50
        ''')
        buyers = cursor.fetchall()

    if not buyers:
        bot.reply_to(message, "No buyers found yet.")
        return

    text = "💰 <b>Top Buyers</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for uid, uname, spent in buyers:
        user_display = f"@{uname}" if uname else f"ID:{uid}"
        text += f"👤 {user_display}\n└ <code>{spent}</code> Stars\n\n"

    bot.send_message(message.chat.id, text, parse_mode='HTML')

@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

# ============================================
# ✅ دالة استلام الدفع - النسخة المصلحة
# ============================================
@bot.message_handler(content_types=['successful_payment'])
def got_payment(message):
    try:
        user_id = message.from_user.id
        username = message.from_user.username
        amount = message.successful_payment.total_amount
        currency = message.successful_payment.currency
        charge_id = message.successful_payment.telegram_payment_charge_id
        lang = get_user_language(user_id)
        payload = message.successful_payment.invoice_payload
        
        print(f"🔍 DEBUG: Payment received - user={user_id}, amount={amount}, currency={currency}, payload='{payload}'")
        
        # ✅ استخراج عدد الفيديوهات بالطريقة الصحيحة
        video_count = 50  # قيمة افتراضية للسلامة
        
        if payload:
            # للصيغة: deliver_userid_count (مثال: deliver_123456_175000)
            if payload.startswith("deliver_") and not payload.startswith("deliver_videos_"):
                parts = payload.split('_')
                if len(parts) >= 3:
                    try:
                        video_count = int(parts[2])
                        print(f"✅ Extracted video count from payload: {video_count}")
                    except ValueError:
                        print(f"⚠️ Could not parse video count from payload part: {parts[2]}")
                        # محاولة استخراج العدد من الـ parts كلها
                        for part in parts:
                            try:
                                potential_count = int(part)
                                if potential_count > 50:
                                    video_count = potential_count
                                    print(f"✅ Found video count from alternative part: {video_count}")
                                    break
                            except:
                                continue
            
            # للصيغة: deliver_videos_499 (العرض الخاص)
            elif payload == "deliver_videos_499":
                video_count = 499
                print(f"✅ Special 499 offer detected")
        
        print(f"📦 Final video count to deliver: {video_count}")
        
        # Admin Notification
        for admin_id in NOTIFY_IDS:
            try:
                bot.send_message(admin_id,
                    f"💰 <b>New Payment Received!</b>\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"👤 <b>User:</b> @{escape_html(username) if username else 'N/A'}\n"
                    f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
                    f"💵 <b>Amount:</b> <code>{amount}</code> {currency}\n"
                    f"📦 <b>Videos Count:</b> <code>{video_count}</code>\n"
                    f"🧾 <b>Charge ID:</b> <code>{charge_id}</code>\n"
                    f"📝 <b>Payload:</b> <code>{payload}</code>",
                    parse_mode='HTML')
            except: pass
        
        # ✅ جلب الفيديوهات وإرسالها
        unsent = get_unsent_videos(user_id, limit=video_count)
        
        if unsent and len(unsent) > 0:
            print(f"✅ Found {len(unsent)} videos to send to user {user_id}")
            
            # إرسال رسالة تأكيد للمستخدم
            try:
                bot.send_message(user_id, 
                    get_string('payment_success', lang, count=len(unsent)), 
                    parse_mode='HTML')
            except Exception as e:
                print(f"⚠️ Could not send confirmation message: {e}")
            
            # وضع الفيديوهات في طابور الإرسال
            delivery_queue.put((user_id, unsent, notify_delivery_success, notify_delivery_failure, None))
            print(f"✅ Videos queued for delivery to user {user_id}")
            
            # حفظ عملية الدفع في قاعدة البيانات
            with sqlite3.connect(DATABASE) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'INSERT OR IGNORE INTO payments (user_id, payment_id, amount, currency) VALUES (?, ?, ?, ?)',
                    (user_id, charge_id, amount, currency)
                )
                conn.commit()
                print(f"✅ Payment record saved to database")
            
            # تحديث里程碑 المستخدم
            update_user_milestone(user_id, amount)
            
        else:
            # لا توجد فيديوهات متاحة
            print(f"⚠️ No videos available for user {user_id}")
            try:
                bot.send_message(user_id, 
                    "❌ Sorry, no videos available at the moment. Please contact admin.",
                    parse_mode='HTML')
            except:
                pass
            
    except Exception as e:
        print(f"❌ CRITICAL ERROR in got_payment: {e}")
        import traceback
        traceback.print_exc()
        # محاولة إبلاغ المستخدم
        try:
            bot.send_message(message.from_user.id, 
                "❌ An error occurred processing your payment. Admin has been notified.")
        except:
            pass
        # إبلاغ الأدمن
        for admin_id in NOTIFY_IDS:
            try:
                bot.send_message(admin_id, 
                    f"🚨 <b>CRITICAL ERROR Processing Payment!</b>\n\n"
                    f"User ID: <code>{message.from_user.id}</code>\n"
                    f"Error: <code>{str(e)}</code>")
            except:
                pass

@bot.message_handler(commands=['db_debug'])
def handle_db_debug(message):
    if not is_admin(message.from_user.id): return
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            total_refs = cursor.execute('SELECT COUNT(*) FROM referrals').fetchone()[0]
            top_5 = cursor.execute('''
                SELECT referrer_id, COUNT(*) as c 
                FROM referrals 
                GROUP BY referrer_id 
                ORDER BY c DESC 
                LIMIT 5
            ''').fetchall()
            total_vids = cursor.execute('SELECT COUNT(*) FROM videos').fetchone()[0]
            total_payments = cursor.execute('SELECT COUNT(*) FROM payments').fetchone()[0]

        text = "🔍 <b>Live DB Debug</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        text += f"📹 Total Videos: <b>{total_vids}</b>\n"
        text += f"👥 Total Referrals: <b>{total_refs}</b>\n"
        text += f"💰 Total Payments: <b>{total_payments}</b>\n\n"
        text += "<b>Top 5 Referrers:</b>\n"
        for rid, count in top_5:
            text += f"└ ID: <code>{rid}</code> - <b>{count}</b> invites\n"

        bot.reply_to(message, text, parse_mode='HTML')
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

@bot.message_handler(commands=['users_count'])
def handle_users_count(message):
    if not is_admin(message.from_user.id): return
    count = get_total_users()
    bot.reply_to(message, f"📊 <b>User Count</b>\n\n👥 Total registered users: <code>{count}</code>", parse_mode='HTML')

@bot.message_handler(commands=['add'])
def handle_add_video(message):
    if not is_admin(message.from_user.id): return
    ADMIN_STATES[message.from_user.id] = 'WAITING_VIDEO'
    bot.send_message(message.chat.id, "📤 Send the videos you want to add. Type /done when finished.")

@bot.message_handler(content_types=['video'])
def handle_video_upload(message):
    if not is_admin(message.from_user.id) or ADMIN_STATES.get(message.from_user.id) != 'WAITING_VIDEO': return
    file_id = message.video.file_id
    file_name = message.video.file_name
    file_size = message.video.file_size
    duration = message.video.duration
    video_id = save_video(file_id, file_name, file_size, duration)

    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        total_vids = cursor.execute('SELECT COUNT(*) FROM videos').fetchone()[0]

    bot.reply_to(message, f"{E_CHECK} Video added! (Total: {total_vids})")

@bot.message_handler(commands=['done'])
def handle_done(message):
    if not is_admin(message.from_user.id): return
    ADMIN_STATES[message.from_user.id] = None
    bot.send_message(message.chat.id, f"{E_CHECK} Upload session finished.")

@bot.message_handler(commands=['videos'])
def handle_videos_list(message):
    if not is_admin(message.from_user.id): return
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        total_vids = cursor.execute('SELECT COUNT(*) FROM videos').fetchone()[0]
        today_vids = cursor.execute("SELECT COUNT(*) FROM videos WHERE date(added_date) = date('now')").fetchone()[0]
        week_vids = cursor.execute("SELECT COUNT(*) FROM videos WHERE added_date >= datetime('now', '-7 days')").fetchone()[0]

    text = (
        f"📹 <b>Video Library Stats</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 <b>Total Videos:</b> <code>{total_vids}</code>\n"
        f"📅 <b>Added Today:</b> <code>{today_vids}</code>\n"
        f"🗓️ <b>Added This Week:</b> <code>{week_vids}</code>\n\n"
        f"✨ Your library is growing!"
    )
    bot.send_message(message.chat.id, text, parse_mode='HTML')

@bot.message_handler(commands=['stats'])
def handle_admin_stats(message):
    if not is_admin(message.from_user.id): return
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        total_users = cursor.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        total_vids = cursor.execute('SELECT COUNT(*) FROM videos').fetchone()[0]
        purchases = cursor.execute('SELECT COUNT(*) FROM payments').fetchone()[0]
        total_referrals = cursor.execute('SELECT COUNT(*) FROM referrals').fetchone()[0]
        total_rewards_claimed = cursor.execute('SELECT COUNT(*) FROM referral_rewards').fetchone()[0]
    bot.send_message(message.chat.id,
        f"📊 <b>Bot Stats</b>\n\n"
        f"👥 Users: {total_users}\n"
        f"📹 Videos: {total_vids}\n"
        f"🛒 Purchases: {purchases}\n"
        f"👥 Total Referrals: {total_referrals}\n"
        f"🎁 Rewards Claimed: {total_rewards_claimed}",
        parse_mode='HTML')

@bot.message_handler(commands=['ban'])
def handle_ban_command(message):
    if not is_admin(message.from_user.id): return
    try:
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, "Usage: /ban <user_id>")
            return
        target_id = int(args[1])
        ban_user(target_id)
        bot.reply_to(message, f"✅ User {target_id} has been banned.")
        log_admin_action(message.from_user.id, "BAN", target_id=target_id)
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

@bot.message_handler(commands=['unban'])
def handle_unban_command(message):
    if not is_admin(message.from_user.id): return
    try:
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, "Usage: /unban <user_id>")
            return
        target_id = int(args[1])
        unban_user(target_id)
        bot.reply_to(message, f"✅ User {target_id} has been unbanned.")
        log_admin_action(message.from_user.id, "UNBAN", target_id=target_id)
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

@bot.message_handler(commands=['send_v'])
def handle_send_v(message):
    if not is_admin(message.from_user.id): return
    try:
        args = message.text.split()
        if len(args) < 3:
            bot.reply_to(message, "Usage: /send_v <user_id> <count>")
            return
        target_id = int(args[1])
        video_count = int(args[2])
        unsent = get_unsent_videos(target_id, limit=video_count)
        if not unsent:
            bot.reply_to(message, "No new videos available for this user.")
            return

        status_msg = bot.send_message(message.chat.id,
            f"🚀 <b>Starting Manual Delivery...</b>\n"
            f"Target: <code>{target_id}</code>\n"
            f"Count: {len(unsent)}", parse_mode='HTML')

        delivery_queue.put((target_id, unsent, notify_delivery_success, notify_delivery_failure, status_msg.message_id))
        log_admin_action(message.from_user.id, "SEND_V", target_id=target_id, details=f"Count: {video_count}")
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

@bot.message_handler(commands=['top_referrers'])
def handle_top_referrers(message):
    if not is_admin(message.from_user.id): return
    leaders = get_referral_leaderboard(20)

    if not leaders:
        bot.reply_to(message, "No referrals yet.")
        return

    text = "🏆 <b>Top Referrers (Admin View)</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for i, (uid, uname, count) in enumerate(leaders):
        display = f"@{uname}" if uname else f"ID:{uid}"
        text += f"#{i+1} {display} — <b>{count}</b> invites (ID: <code>{uid}</code>)\n"

    bot.send_message(message.chat.id, text, parse_mode='HTML')

@bot.message_handler(commands=['broadcast_all'])
def handle_broadcast(message):
    if not is_admin(message.from_user.id): return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.reply_to(message, "Usage: /broadcast_all <message>")
        return

    broadcast_text = args[1]
    conn = sqlite3.connect(DATABASE)
    users = [r[0] for r in conn.execute('SELECT user_id FROM users').fetchall()]
    conn.close()

    success, fail = 0, 0
    for uid in users:
        try:
            bot.send_message(uid, broadcast_text, parse_mode='HTML')
            success += 1
            time.sleep(0.05)
        except:
            fail += 1

    bot.reply_to(message, f"📢 Broadcast Complete!\n✅ Success: {success}\n❌ Failed: {fail}")
    log_admin_action(message.from_user.id, "BROADCAST_ALL", details=f"Success: {success}, Failed: {fail}")

@bot.message_handler(commands=['promo'])
def handle_promo(message):
    if not is_admin(message.from_user.id): return

    fire_line = "🔥" * 10
    star_line = "⭐" * 10
    diamond_line = "💎" * 10

    promo_text = (
        f"{fire_line}\n\n"
        f"🎬 <b>PREMIUM EXCLUSIVE VIDEOS</b> 🎬\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👑 <b>The #1 Premium Video Bot on Telegram!</b>\n\n"
        f"💎 <b>What You Get:</b>\n"
        f"├ 🎥 High-quality exclusive content\n"
        f"├ ⚡ Instant delivery to your chat\n"
        f"├ 🎁 FREE videos through referrals\n"
        f"└ 🏆 6 reward tiers to unlock\n\n"
        f"{star_line}\n\n"
        f"👥 <b>INVITE & EARN FREE VIDEOS:</b>\n\n"
        f"🥉 2 invites = 10 free videos\n"
        f"🥈 5 invites = 25 free videos\n"
        f"🥇 10 invites = 50 free videos\n"
        f"💎 25 invites = 125 free videos\n"
        f"💠 50 invites = 250 free videos\n"
        f"👑 100 invites = 500 free videos\n"
        f"🔥 200 invites = 1000 free videos\n\n"
        f"<b>Join our channel:</b> https://t.me/+_U7Ve8BeTaVjY2Y1\n\n"
        f"{diamond_line}\n\n"
        f"🔥 <b>TOTAL: Up to 1960 FREE VIDEOS!</b> 🔥\n\n"
        f"👇 <b>TAP BELOW TO START NOW!</b> 👇"
    )

    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("🚀 START THE BOT NOW 🚀", url="https://t.me/Llllppppooottt_bot?start=promo"))

    bot.send_message(message.chat.id, promo_text, parse_mode='HTML', reply_markup=keyboard)
    log_admin_action(message.from_user.id, "PROMO_GENERATED")

@bot.message_handler(commands=['share'])
def handle_share_broadcast(message):
    if not is_admin(message.from_user.id):
        return

    lang = 'en'
    global BOT_USERNAME
    if not BOT_USERNAME: BOT_USERNAME = bot.get_me().username
    
    invite_link = f"https://t.me/{BOT_USERNAME}?start={message.from_user.id}"
    share_text = f"🔥 {get_emoji_tag('FIRE', '🔥')} <b>STAY MOTIVATED!</b> {get_emoji_tag('FIRE', '🔥')}\n\n" \
                 f"✨ {get_emoji_tag('STAR_GOLD', '✨')} <b>Success is a journey, not a destination!</b>\n" \
                 f"🚀 {get_emoji_tag('PLANE', '🚀')} <b>Push yourself because no one else is going to do it for you!</b>\n\n" \
                 f"🎁 {get_emoji_tag('GIFT', '🎁')} <b>Share this bot with your friends and earn FREE premium videos!</b>\n\n" \
                 f"👇 <b>Invite & Earn Now</b> 👇"
                 
    import urllib.parse
    share_url = f"https://t.me/share/url?url={urllib.parse.quote(invite_link)}&text={urllib.parse.quote('Check out this amazing bot! 🎬')}"
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("📤 SHARE & EARN VIDEOS", url=share_url))
    
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM users')
        users = cursor.fetchall()
        
    count = 0
    for (u_id,) in users:
        try:
            bot.send_message(u_id, share_text, parse_mode='HTML', reply_markup=keyboard)
            count += 1
            time.sleep(0.05)
        except:
            continue
            
    bot.reply_to(message, f"✅ Broadcast sent to {count} users.")

@bot.message_handler(func=lambda message: True)
def echo_all(message):
    save_user(message.from_user.id, message.from_user.username)

# ============================================
# بدء تشغيل البوت
# ============================================
init_db()
flask_thread = Thread(target=run_flask)
flask_thread.daemon = True
flask_thread.start()

print("=" * 50)
print("🤖 Bot is starting...")
print(f"📁 Database: {os.path.abspath(DATABASE)}")
print(f"👑 Admin IDs: {ADMIN_IDS}")
print("=" * 50)

while True:
    try:
        bot.remove_webhook()
        bot.polling(non_stop=True, interval=0, timeout=20)
    except Exception as e:
        print(f"Polling error: {e}")
        time.sleep(5)
