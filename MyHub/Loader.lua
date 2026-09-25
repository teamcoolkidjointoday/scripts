-- ==================================================
-- MYHUB | LOADER (FINAL)
-- Структура: Versions, Obusik, GivGet, Fixap, function, menu
-- ==================================================

local BASE_URL = "https://raw.githubusercontent.com/teamcoolkidjointoday/MyHub/main/"

_G.MYHUB = _G.MYHUB or {}
_G.MYHUB.Cache = {}
_G.MYHUB.EnablePrint = true

local function log(...)
    if _G.MYHUB.EnablePrint then print("[MYHUB]", ...) end
end

local function GetScript(path)
    local fullPath = BASE_URL .. path
    if _G.MYHUB.Cache[fullPath] then
        return _G.MYHUB.Cache[fullPath]
    end
    local ok, src = pcall(game.HttpGet, game, fullPath)
    if not ok or not src then
        warn("[MYHUB] Не удалось скачать: " .. fullPath)
        return nil
    end
    _G.MYHUB.Cache[fullPath] = src
    return src
end

local function SafeLoad(path)
    log("Загрузка " .. path .. "...")
    local src = GetScript(path)
    if not src then return end
    local ok, err = pcall(function()
        loadstring(src)()
    end)
    if not ok then
        warn("[MYHUB] Ошибка в " .. path .. ": " .. tostring(err))
    end
end

-- Ожидание загрузки игры
repeat task.wait() until game:IsLoaded() and game.Players.LocalPlayer
log("Игра загружена. Игрок: " .. game.Players.LocalPlayer.Name)

-- ==================================================
-- ЗАГРУЗКА (порядок важен!)
-- ==================================================

-- 1. Функции (ядро)
SafeLoad("function/AuraMenu.txt")
SafeLoad("function/FlingMenu.txt")
SafeLoad("function/GunEsp.txt")
SafeLoad("function/SilentAim.txt")

-- 2. Версии
SafeLoad("Versions/kitifatalMenu.txt")
SafeLoad("Versions/kitiv3menu.txt")
SafeLoad("Versions/kitiv4menu.txt")
SafeLoad("Versions/kiti0ldV2.txt")

-- 3. Obusik
SafeLoad("Obusik/KitiObfV3B.txt")
SafeLoad("Obusik/KitiObfV3BFix.txt")
SafeLoad("Obusik/KitiObfV4B.txt")

-- 4. Fixap
SafeLoad("Fixap/kitiv4menu.txt")

-- 5. GivGet
SafeLoad("GivGet/kitiv4menu.txt")

-- 6. Меню
SafeLoad("menu/FatalityMenu100.txt")
SafeLoad("menu/FatalitySkeletMenu.txt")
SafeLoad("menu/FatalitySPFUMenu.txt")
SafeLoad("menu/FatalitySPIMenu.txt")
SafeLoad("menu/info.txt")
SafeLoad("menu/menuderevo1.txt")

log("Все модули загружены!")
print("🚀 MYHUB | Ready!")