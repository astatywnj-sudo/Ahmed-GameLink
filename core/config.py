"""Ahmed GameLink — central configuration (Spec section 8.4).

All network targets and limits live here so they can be updated without
touching engine or UI code.

Endpoints are PUBLIC health-check URLs: they require no login, no cookies,
and no Roblox account. Nothing here identifies or stores a user.
"""

# ------------------------------------------------------------------ identity
APP_NAME = "Ahmed GameLink"
APP_VERSION = "0.1.0"

# ------------------------------------------------- diagnostics limits (8.1/5)
CHECK_TIMEOUT_SECONDS = 10      # hard cap per single check (Spec section 5)
TOTAL_BUDGET_SECONDS = 45       # worst-case full diagnostic run

# ---------------------------------------------------- Roblox endpoints (8.4)
# (url, short description shown in the UI)
ROBLOX_ENDPOINTS = {
    "web":        ("https://www.roblox.com/home", "الموقع الرئيسي"),
    "apis":       ("https://apis.roblox.com/user/profile/get-rbac-permissions", "خدمة APIs العامة"),
    "thumbnails": ("https://thumbnails.roblox.com/v1/batch", "خدمة الصور المصغّرة"),
    "game_join":  ("https://gamejoin.roblox.com/", "خدمة الانضمام للألعاب"),
    "presence":   ("https://presence.roblox.com/", "خدمة الحضور"),
    "friends":    ("https://friends.roblox.com/", "خدمة الأصدقاء"),
    "client_api": ("https://clientsettings.roblox.com/v2/client-version/WindowsStudio64",
                   "إعدادات العميل"),
    # Public mirrors used only when the main domains themselves are blocked:
    "proxy_web":  ("https://www.roproxy.com/home", "مرآة roproxy"),
    "proxy_apis": ("https://apis.roproxy.com/", "مرآة roproxy API"),
}

# --------------------------------------------------------- DNS targets (8.4)
# "system" means the DNS resolver configured by Windows for this machine.
DNS_SERVERS = [
    ("system", "خادم DNS الحالي للنظام"),
    ("1.1.1.1", "Cloudflare"),
    ("8.8.8.8", "Google"),
    ("9.9.9.9", "Quad9"),
]

# Well-known connectivity probe used for the "is there internet at all?"
# step: returns HTTP 204 with a tiny body, cheap on metered connections.
INTERNET_PROBE_URL = "https://www.google.com/generate_204"
