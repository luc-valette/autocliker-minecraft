#!/usr/bin/env python3
"""
Minecraft Auto-Crafter
======================
Fichiers :
  main.py       Ce fichier (tout le code)
  crafts.json   Les recettes de craft
  maps.json     Les maps de calibration et timings
  presets.json   Les presets sauvegardes (cree automatiquement)

Compatible macOS et Windows.

Installation macOS :
    pip install pyautogui pyobjc-framework-Quartz pynput Pillow

Installation Windows :
    pip install pyautogui pynput Pillow

Permissions macOS :
    Preferences Systeme > Confidentialite > Accessibilite > Terminal

Ligne de commande :
    python main.py                                          Menu interactif
    python main.py preset <nom>                             Lancer un preset
    python main.py phase1 --map <m> --slots <s>             Phase 1
    python main.py phase2 --map <m> --recipe <r> --slots <s>  Phase 2
    python main.py complet --map <m> --recipe <r> --p1slots <s> --p2slots <s>
    python main.py list-presets                              Lister les presets
"""

import pyautogui
import time
import json
import os
import sys
import platform as platform_mod
import threading
import argparse
from pynput import keyboard

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def detect_platform():
    system = platform_mod.system().lower()
    if system == "darwin":
        return "mac"
    elif system == "windows":
        return "windows"
    return system


CURRENT_PLATFORM = detect_platform()


###########################################################
#  STOP HANDLER
###########################################################

_stop_flag = threading.Event()


class StopException(Exception):
    pass


def _on_key_press(key):
    try:
        if key.char in ("m", "M"):
            _stop_flag.set()
            print("\n  >>> ARRET DEMANDE (touche M) <<<\n")
    except AttributeError:
        pass


def start_stop_listener():
    _stop_flag.clear()
    listener = keyboard.Listener(on_press=_on_key_press)
    listener.daemon = True
    listener.start()
    return listener


def check_stop():
    if _stop_flag.is_set():
        raise StopException("Arret par touche M")


###########################################################
#  GUI CHECK (3 pixels, vote majoritaire 2/3)
###########################################################

_click_counter = 0
_gui_ref_positions = None


def set_gui_ref(positions):
    global _gui_ref_positions, _click_counter
    _gui_ref_positions = positions
    _click_counter = 0


def clear_gui_ref():
    global _gui_ref_positions
    _gui_ref_positions = None


def check_gui_open():
    """Verifie 3 pixels de reference. Arret si 2/3 ont change."""
    global _click_counter
    _click_counter += 1

    interval = int(TIMINGS.get("gui_check_interval", 1))
    if interval <= 0 or _gui_ref_positions is None:
        return
    if "gui_refs" not in _gui_ref_positions:
        return
    if _click_counter % interval != 0:
        return

    refs = _gui_ref_positions["gui_refs"]
    tolerance = int(TIMINGS.get("gui_tolerance", 60))
    changed_count = 0

    for ref in refs:
        rx, ry = ref["pos"]
        ref_color = tuple(ref["color"])
        try:
            screenshot = pyautogui.screenshot(region=(rx, ry, 1, 1))
            current = screenshot.getpixel((0, 0))[:3]
            diff = sum(abs(a - b) for a, b in zip(current, ref_color))
            if diff > tolerance * 3:
                changed_count += 1
        except Exception:
            pass

    if changed_count >= 2:
        _stop_flag.set()
        print(f"\n  >>> GUI FERMEE ({changed_count}/3 pixels changes) <<<\n")
        raise StopException("GUI fermee, arret automatique")


###########################################################
#  CONFIG
###########################################################

CONFIG_FILE = os.path.join(SCRIPT_DIR, "maps.json")

DEFAULT_TIMINGS = {
    "action_delay": 0.3,
    "shift_delay": 0.1,
    "craft_output_delay": 0.3,
    "drop_delay": 0.3,
    "countdown": 5,
    "gui_check_interval": 1,
    "gui_tolerance": 60,
}

TIMING_KEYS_BATCH = ["action_delay", "shift_delay", "craft_output_delay", "drop_delay"]
TIMING_KEYS_ALL = TIMING_KEYS_BATCH + ["countdown", "gui_check_interval", "gui_tolerance"]

TIMING_LABELS = {
    "action_delay":       "Delai apres chaque clic standard",
    "shift_delay":        "Delai autour du shift",
    "craft_output_delay": "Delai apres clic sur la sortie",
    "drop_delay":         "Delai apres le drop hors GUI",
    "countdown":          "Compte a rebours (secondes)",
    "gui_check_interval": "Verification GUI tous les N clics (0 = desactive)",
    "gui_tolerance":      "Tolerance couleur GUI (plus bas = plus sensible)",
}

TIMINGS = dict(DEFAULT_TIMINGS)


def apply_timings(config, map_data):
    global_timings = config.get("timings", DEFAULT_TIMINGS)
    for key in TIMING_KEYS_ALL:
        TIMINGS[key] = global_timings.get(key, DEFAULT_TIMINGS.get(key))
    if map_data and "timings" in map_data:
        for key in TIMING_KEYS_ALL:
            if key in map_data["timings"]:
                TIMINGS[key] = map_data["timings"][key]


def map_has_custom_timings(map_data):
    return map_data is not None and "timings" in map_data


def map_has_custom_platform(config, map_data):
    if map_data is None or "platform" not in map_data:
        return False
    return map_data["platform"] != config.get("platform", CURRENT_PLATFORM)


def get_map_platform(config, map_data):
    if map_data and "platform" in map_data:
        return map_data["platform"]
    return config.get("platform", CURRENT_PLATFORM)


def map_display_name(name, map_data, config=None):
    suffixes = []
    if map_has_custom_timings(map_data):
        suffixes.append("timing_modifie")
    if config and map_has_custom_platform(config, map_data):
        suffixes.append(get_map_platform(config, map_data))
    if suffixes:
        return f"{name}_{'_'.join(suffixes)}"
    return name


def load_config():
    if not os.path.exists(CONFIG_FILE):
        return None, None
    with open(CONFIG_FILE) as f:
        config = json.load(f)

    if "maps" not in config:
        print("  Migration de l'ancien format de config...")
        old_map = {}
        keys_to_move = [
            "craft_1", "craft_2", "craft_3", "craft_4", "craft_5",
            "craft_6", "craft_7", "craft_8", "craft_9",
            "output", "drop_zone", "inv_origin", "inv_spacing", "hotbar_origin",
        ]
        for k in keys_to_move:
            if k in config:
                old_map[k] = config.pop(k)
        config["maps"] = {"default": old_map}
        config["active_map"] = "default"
        if "timings" not in config:
            config["timings"] = dict(DEFAULT_TIMINGS)
        save_config(config)
        print("  Migration terminee.\n")

    modified = False
    if "timings" not in config:
        config["timings"] = dict(DEFAULT_TIMINGS)
        modified = True
    else:
        for key, val in DEFAULT_TIMINGS.items():
            if key not in config["timings"]:
                config["timings"][key] = val
                modified = True
    if "platform" not in config:
        config["platform"] = CURRENT_PLATFORM
        modified = True
    if modified:
        save_config(config)

    active_name = config.get("active_map", "")
    map_data = None
    if active_name and active_name in config.get("maps", {}):
        map_data = config["maps"][active_name]
    apply_timings(config, map_data)
    return config, map_data


def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def get_active_map_or_warn(config):
    if config is None:
        print("  Aucune config trouvee. Lance la calibration.\n")
        return None
    active_name = config.get("active_map", "")
    if not active_name or active_name not in config.get("maps", {}):
        print("  Aucune map active.\n")
        return None
    return config["maps"][active_name]


def get_map_by_name(config, name):
    """Retourne une map par son nom, ou None."""
    if config and name in config.get("maps", {}):
        apply_timings(config, config["maps"][name])
        return config["maps"][name]
    return None


def edit_timings(config):
    if config is None:
        config = {"maps": {}, "timings": dict(DEFAULT_TIMINGS), "active_map": "", "platform": CURRENT_PLATFORM}

    active_name = config.get("active_map", "")
    active_map = config["maps"].get(active_name) if active_name else None
    has_custom = map_has_custom_timings(active_map)
    map_plat = get_map_platform(config, active_map) if active_name else None

    print("\n--- MODIFIER LES TIMINGS ---\n")
    print(f"  G. Timings GLOBAUX")
    if active_name:
        custom_tag = " (personnalises)" if has_custom else " (globaux)"
        print(f"  M. Timings de la map '{active_name}'{custom_tag}")
        if has_custom:
            print(f"  R. Reinitialiser la map aux timings globaux")
        print(f"  P. Plateforme de la map '{active_name}' (actuel : {map_plat})")
    print(f"  0. Retour\n")

    scope = input("  Choix : ").strip().lower()

    if scope == "0":
        return config
    if scope == "r" and active_name and has_custom:
        del active_map["timings"]
        apply_timings(config, active_map)
        save_config(config)
        print(f"\n  Timings reinitialises.\n")
        return config
    if scope == "p" and active_name:
        default_plat = config.get("platform", CURRENT_PLATFORM)
        new_plat = input(f"  Plateforme (mac/windows, D=defaut) : ").strip().lower()
        if new_plat == "d":
            active_map.pop("platform", None)
            save_config(config)
            print(f"  Remis au defaut ({default_plat}).\n")
        elif new_plat in ("mac", "windows"):
            active_map["platform"] = new_plat
            save_config(config)
            print(f"  Plateforme : {new_plat}.\n")
        return config

    if scope == "g":
        target_timings = config.get("timings", dict(DEFAULT_TIMINGS))
        target_label = "GLOBAUX"
    elif scope == "m" and active_name:
        target_timings = active_map.get("timings", dict(config.get("timings", DEFAULT_TIMINGS)))
        if not has_custom:
            target_timings = dict(config.get("timings", DEFAULT_TIMINGS))
        target_label = f"MAP '{active_name}'"
    else:
        print("  Choix invalide.\n")
        return config

    print(f"\n  Timings {target_label} :\n")
    for i, key in enumerate(TIMING_KEYS_ALL):
        print(f"  {i + 1}. {key} = {target_timings.get(key, DEFAULT_TIMINGS[key])}"
              f"  ({TIMING_LABELS[key]})")
    print(f"\n  A. Modifier les delais 1 a 4 d'un coup")
    print(f"  0. Retour\n")

    choice = input("  Choix : ").strip()
    if choice == "0":
        return config

    if choice.lower() == "a":
        val = input("\n  Valeur pour les delais 1 a 4 : ").strip()
        if val:
            try:
                new_val = float(val)
                for key in TIMING_KEYS_BATCH:
                    target_timings[key] = new_val
            except ValueError:
                print("  Invalide.\n")
                return config
    else:
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(TIMING_KEYS_ALL):
                key = TIMING_KEYS_ALL[idx]
                current = target_timings.get(key, DEFAULT_TIMINGS[key])
                val = input(f"  {key} [{current}] : ").strip()
                if val:
                    target_timings[key] = float(val)
            else:
                print("  Invalide.\n")
                return config
        except ValueError:
            print("  Invalide.\n")
            return config

    if scope == "g":
        config["timings"] = target_timings
    elif scope == "m" and active_name:
        active_map["timings"] = target_timings
    apply_timings(config, active_map)
    save_config(config)
    print(f"\n  Sauvegardes.\n")
    return config


###########################################################
#  UTILS
###########################################################

def safe_click(x, y, button="left", delay=None):
    check_stop()
    check_gui_open()
    pyautogui.click(x, y, button=button)
    time.sleep(delay if delay is not None else TIMINGS["action_delay"])


def shift_click(x, y):
    check_stop()
    check_gui_open()
    sd = TIMINGS["shift_delay"]
    pyautogui.keyDown("shift")
    time.sleep(sd)
    pyautogui.click(x, y)
    time.sleep(sd)
    pyautogui.keyUp("shift")
    time.sleep(TIMINGS["action_delay"])


def inv_pos(positions, slot_index):
    sx, sy = positions["inv_spacing"]
    if slot_index < 27:
        row = slot_index // 9
        col = slot_index % 9
        ox, oy = positions["inv_origin"]
        return (ox + col * sx, oy + row * sy)
    else:
        col = slot_index - 27
        ox, oy = positions["hotbar_origin"]
        return (ox + col * sx, oy)


def countdown():
    seconds = int(TIMINGS["countdown"])
    print(f"\nRetourne sur Minecraft ! Debut dans {seconds} secondes...")
    print("(Touche M = arret)\n")
    for i in range(seconds, 0, -1):
        print(f"  {i}...")
        time.sleep(1)
    print("  C'est parti !\n")


def parse_slots(text):
    slots = []
    parts = text.replace(",", " ").split()
    for part in parts:
        if "-" in part:
            start, end = part.split("-", 1)
            slots.extend(range(int(start), int(end) + 1))
        else:
            slots.append(int(part))
    return slots


def stack_size_label(size):
    if size == 1:
        return "non stackable, drop"
    return f"stackable par {size}"


def format_duration(seconds):
    """Formate une duree en mm:ss."""
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


###########################################################
#  CALIBRATION
###########################################################

def calibrate(config):
    if config is None:
        config = {"maps": {}, "timings": dict(DEFAULT_TIMINGS), "active_map": "", "platform": CURRENT_PLATFORM}

    print("\n" + "=" * 50)
    print("  CALIBRATION")
    print("=" * 50)

    existing = list(config.get("maps", {}).keys())
    if existing:
        print(f"\n  Maps existantes : {', '.join(existing)}")
    name = input("\n  Nom de cette map : ").strip()
    if not name:
        print("  Annulation.\n")
        return config
    if name in config.get("maps", {}):
        if input(f"  Ecraser '{name}' ? (o/n) : ").strip().lower() != "o":
            return config

    print(f"\n  Ouvre ta TABLE DE CRAFT dans Minecraft.\n")

    positions = {}
    grid_labels = [
        ("craft_1", "HAUT-GAUCHE   (1)"), ("craft_2", "HAUT-CENTRE   (2)"),
        ("craft_3", "HAUT-DROITE   (3)"), ("craft_4", "MILIEU-GAUCHE (4)"),
        ("craft_5", "MILIEU-CENTRE (5)"), ("craft_6", "MILIEU-DROITE (6)"),
        ("craft_7", "BAS-GAUCHE    (7)"), ("craft_8", "BAS-CENTRE    (8)"),
        ("craft_9", "BAS-DROITE    (9)"),
    ]

    for key, label in grid_labels:
        input(f"  -> {label}  ... [Entree]")
        pos = pyautogui.position()
        positions[key] = [pos.x, pos.y]
        print(f"     OK ({pos.x}, {pos.y})\n")

    input("  -> SLOT DE SORTIE  ... [Entree]")
    pos = pyautogui.position()
    positions["output"] = [pos.x, pos.y]
    print(f"     OK\n")

    input("  -> ZONE DE DROP (hors GUI)  ... [Entree]")
    pos = pyautogui.position()
    positions["drop_zone"] = [pos.x, pos.y]
    print(f"     OK\n")

    # 3 pixels de reference GUI
    print("--- 3 pixels de reference GUI ---\n")
    print("  Pointe 3 endroits distincts de la GUI (bord gris, fleche, texte).")
    print("  Le script s'arrete si 2/3 changent de couleur.\n")

    gui_refs = []
    for i in range(3):
        input(f"  -> Pixel GUI {i + 1}/3  ... [Entree]")
        pos = pyautogui.position()
        try:
            screenshot = pyautogui.screenshot(region=(pos.x, pos.y, 1, 1))
            color = list(screenshot.getpixel((0, 0))[:3])
        except Exception:
            color = [198, 198, 198]
        gui_refs.append({"pos": [pos.x, pos.y], "color": color})
        print(f"     OK ({pos.x}, {pos.y}) couleur {color}\n")

    positions["gui_refs"] = gui_refs

    # Inventaire
    print("--- Inventaire ---\n")
    input("  -> PREMIER slot (L1, C1)  ... [Entree]")
    pos = pyautogui.position()
    positions["inv_origin"] = [pos.x, pos.y]
    print(f"     OK\n")

    input("  -> DEUXIEME slot (L1, C2)  ... [Entree]")
    pos = pyautogui.position()
    sx = pos.x - positions["inv_origin"][0]
    print(f"     Espacement H : {sx} px\n")

    input("  -> PREMIER slot LIGNE 2  ... [Entree]")
    pos = pyautogui.position()
    sy = pos.y - positions["inv_origin"][1]
    print(f"     Espacement V : {sy} px\n")

    positions["inv_spacing"] = [sx, sy]

    input("  -> PREMIER slot HOTBAR  ... [Entree]")
    pos = pyautogui.position()
    positions["hotbar_origin"] = [pos.x, pos.y]
    print(f"     OK\n")

    if "maps" not in config:
        config["maps"] = {}
    config["maps"][name] = positions
    config["active_map"] = name
    save_config(config)
    print(f"  Map '{name}' sauvegardee et activee.\n")
    return config


def manage_maps(config):
    if config is None:
        print("  Aucune config.\n")
        return config
    maps = config.get("maps", {})
    active = config.get("active_map", "")
    default_platform = config.get("platform", CURRENT_PLATFORM)

    print("\n--- MAPS ---\n")
    print(f"  Plateforme par defaut : {default_platform}\n")
    names = list(maps.keys())
    for i, name in enumerate(names):
        display = map_display_name(name, maps[name], config)
        plat = get_map_platform(config, maps[name])
        marker = " (active)" if name == active else ""
        print(f"  {i + 1}. {display} [{plat}]{marker}")

    print(f"\n  D. Supprimer  |  P. Plateforme par defaut  |  0. Retour\n")
    choice = input("  Choix : ").strip()

    if choice == "0":
        return config
    if choice.lower() == "p":
        new_plat = input(f"  Plateforme (mac/windows) : ").strip().lower()
        if new_plat in ("mac", "windows"):
            config["platform"] = new_plat
            save_config(config)
    elif choice.lower() == "d":
        idx = input("  Numero : ").strip()
        try:
            idx = int(idx) - 1
            if 0 <= idx < len(names):
                del config["maps"][names[idx]]
                if config["active_map"] == names[idx]:
                    remaining = list(config["maps"].keys())
                    config["active_map"] = remaining[0] if remaining else ""
                save_config(config)
                print(f"  Supprimee.\n")
        except (ValueError, IndexError):
            pass
    else:
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(names):
                config["active_map"] = names[idx]
                save_config(config)
                apply_timings(config, config["maps"][names[idx]])
                print(f"  '{names[idx]}' activee.\n")
        except ValueError:
            pass
    return config


def test_calibration(positions):
    print("\n--- TEST ---\n")
    input("  Ouvre ta table de craft et [Entree]...")
    time.sleep(2)

    for key, label in [("craft_1", "Haut-gauche"), ("craft_5", "Centre"),
                       ("craft_9", "Bas-droite"), ("output", "Sortie"),
                       ("drop_zone", "Drop zone")]:
        if key in positions:
            x, y = positions[key]
            print(f"  -> {label} ({x}, {y})")
            pyautogui.moveTo(x, y, duration=0.5)
            time.sleep(0.8)

    if "gui_refs" in positions:
        for i, ref in enumerate(positions["gui_refs"]):
            rx, ry = ref["pos"]
            print(f"  -> Pixel GUI {i+1}/3 ({rx}, {ry}) ref={ref['color']}")
            pyautogui.moveTo(rx, ry, duration=0.3)
            try:
                sc = pyautogui.screenshot(region=(rx, ry, 1, 1))
                cur = list(sc.getpixel((0, 0))[:3])
                diff = sum(abs(a - b) for a, b in zip(cur, ref["color"]))
                status = "OK" if diff <= 180 else "DIFFERENT"
                print(f"     actuel={cur} {status}")
            except Exception as e:
                print(f"     Erreur : {e}")
            time.sleep(0.5)

    for slot, label in [(0, "Inv 0"), (8, "Inv 8"), (27, "Hotbar 27")]:
        pos = inv_pos(positions, slot)
        print(f"  -> {label} ({pos[0]}, {pos[1]})")
        pyautogui.moveTo(pos[0], pos[1], duration=0.5)
        time.sleep(0.8)

    print("\n  Termine.\n")


###########################################################
#  RECIPES
###########################################################

CRAFTS_FILE = os.path.join(SCRIPT_DIR, "crafts.json")


def load_recipes():
    if not os.path.exists(CRAFTS_FILE):
        print(f"  Fichier introuvable : {CRAFTS_FILE}")
        return [], []
    with open(CRAFTS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    categories = data.get("categories", [])
    all_recipes = []
    for cat in categories:
        all_recipes.extend(cat.get("recipes", []))
    return categories, all_recipes


def find_recipe_by_name(name):
    """Trouve une recette par son nom (insensible a la casse)."""
    _, all_recipes = load_recipes()
    for r in all_recipes:
        if r["name"].lower() == name.lower():
            return dict(r)
    return None


def choose_recipe():
    categories, all_recipes = load_recipes()
    if not all_recipes:
        print("  Aucune recette.\n")
        return None

    print("\n--- CHOIX DU CRAFT ---\n")
    num = 1
    for cat in categories:
        print(f"  {cat['label']} :")
        for r in cat["recipes"]:
            nb = len(r["pattern"])
            print(f"    {num}. {r['name']} ({nb} mat., {stack_size_label(r['stack_size'])})")
            for line in r["display"]:
                print(f"         {line}")
            num += 1
        print()
    print(f"  {num}. Personnalise\n")

    choice = input("  Ton choix : ").strip()
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(all_recipes):
            recipe = dict(all_recipes[idx])
            print(f"\n  Selection : {recipe['name']} ({stack_size_label(recipe['stack_size'])})")
            if "note" in recipe:
                print(f"    {recipe['note']}")
            print()
            return recipe
        elif idx == len(all_recipes):
            return create_custom_recipe()
    except ValueError:
        pass
    print("  Invalide.\n")
    return None


def create_custom_recipe():
    print("\n--- PERSONNALISE ---\n")
    print("    1  2  3\n    4  5  6\n    7  8  9\n")
    slots_input = input("  Slots (ex: 1,2,3,5,8) : ").strip()
    try:
        slot_nums = [int(x.strip()) for x in slots_input.split(",")]
        pattern = [f"craft_{n}" for n in slot_nums if 1 <= n <= 9]
    except ValueError:
        return None
    if not pattern:
        return None

    stackable = input("  Stackable ? (o/n) : ").strip().lower() == "o"
    stack_size = 1
    if stackable:
        s = input("  Taille stack [64] : ").strip()
        stack_size = int(s) if s else 64

    grid = [["." for _ in range(3)] for _ in range(3)]
    for n in slot_nums:
        if 1 <= n <= 9:
            grid[(n-1)//3][(n-1)%3] = "X"

    return {
        "name": "Personnalise",
        "pattern": pattern,
        "stack_size": max(1, stack_size),
        "display": [" ".join(r) for r in grid],
    }


###########################################################
#  PRESETS
###########################################################

PRESETS_FILE = os.path.join(SCRIPT_DIR, "presets.json")


def load_presets():
    if not os.path.exists(PRESETS_FILE):
        return {}
    with open(PRESETS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("presets", {})


def save_presets(presets):
    with open(PRESETS_FILE, "w") as f:
        json.dump({"presets": presets}, f, indent=2)


def make_preset(description, map_name, mode, recipe_name=None,
                p1_slots=None, p1_stack=None, p2_slots=None, cycles=None):
    """Cree un preset avec tous les champs (None pour ceux inutilises)."""
    return {
        "description": description,
        "map": map_name,
        "mode": mode,
        "recipe": recipe_name,
        "phase1_slots": p1_slots,
        "phase1_stack_size": p1_stack,
        "phase2_slots": p2_slots,
        "cycles": cycles,
    }


def propose_save_preset(config, mode, recipe=None,
                        p1_slots_str=None, p1_stack=None, p2_slots_str=None, cycles=None):
    """Propose de sauvegarder le craft en preset apres execution."""
    answer = input("  Sauvegarder ce craft comme preset ? (o/n) : ").strip().lower()
    if answer != "o":
        return

    name = input("  Nom du preset : ").strip()
    if not name:
        return
    desc = input("  Description (optionnel) : ").strip() or None

    map_name = config.get("active_map", "")
    recipe_name = recipe["name"] if recipe else None

    preset = make_preset(desc, map_name, mode, recipe_name,
                         p1_slots_str, p1_stack, p2_slots_str, cycles)

    presets = load_presets()
    presets[name] = preset
    save_presets(presets)
    print(f"  Preset '{name}' sauvegarde.\n")


def choose_preset():
    """Affiche les presets et retourne (nom, preset) ou (None, None)."""
    presets = load_presets()
    if not presets:
        print("  Aucun preset.\n")
        return None, None

    print("\n--- PRESETS ---\n")
    names = list(presets.keys())
    for i, name in enumerate(names):
        p = presets[name]
        desc = p.get("description") or ""
        mode = p.get("mode", "?")
        recipe = p.get("recipe") or ""
        cycles = p.get("cycles")
        cycles_str = "infini" if cycles == 0 else str(cycles) if cycles else "1"
        print(f"  {i+1}. {name} [{mode}] {recipe} ({cycles_str} cycles) {desc}")
    print(f"\n  0. Retour\n")

    choice = input("  Choix : ").strip()
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(names):
            return names[idx], presets[names[idx]]
    except ValueError:
        pass
    return None, None


def manage_presets():
    """Sous-menu de gestion des presets."""
    presets = load_presets()
    if not presets:
        print("  Aucun preset.\n")
        return

    print("\n--- GERER LES PRESETS ---\n")
    names = list(presets.keys())
    for i, name in enumerate(names):
        p = presets[name]
        desc = p.get("description") or ""
        print(f"  {i+1}. {name} : {desc}")
    print(f"\n  D. Supprimer  |  0. Retour\n")

    choice = input("  Choix : ").strip()
    if choice.lower() == "d":
        idx = input("  Numero : ").strip()
        try:
            idx = int(idx) - 1
            if 0 <= idx < len(names):
                del presets[names[idx]]
                save_presets(presets)
                print(f"  '{names[idx]}' supprime.\n")
        except (ValueError, IndexError):
            pass


###########################################################
#  CRAFTING (avec timer et boucle auto)
###########################################################

RESUPPLY_PAUSE = 45  # secondes de pause pour reapprovisionnement


def phase_blocks_to_ingots(positions, block_slots, stack_size=64):
    craft_center = positions["craft_5"]
    output = positions["output"]
    total = 0
    for slot in block_slots:
        pos = inv_pos(positions, slot)
        print(f"  [Phase 1] Slot {slot} : {stack_size} blocs...")
        safe_click(pos[0], pos[1])
        safe_click(craft_center[0], craft_center[1])
        shift_click(output[0], output[1])
        total += stack_size * 9
        print(f"           {stack_size * 9} lingots.\n")
    print(f"  [Phase 1] Total : {total} lingots.\n")
    return total


def phase_craft(positions, recipe, ingot_slots, total_cycles=1):
    """
    Phase 2 generique avec timer et boucle automatique.

    total_cycles : nombre de cycles a executer.
      1 = un passage (defaut)
      0 = boucle infinie avec reapprovisionnement
      N = exactement N cycles
      valeur negative = un seul passage complet, sans boucle ni pause
        (utilise par full_auto, qui pilote lui-meme la boucle et le
        reapprovisionnement des blocs)
    """
    pattern = recipe["pattern"]
    num_slots = len(pattern)
    output = positions["output"]
    stack_size = recipe["stack_size"]

    cycles_per_pass = len(ingot_slots) // num_slots
    leftover = len(ingot_slots) % num_slots

    if cycles_per_pass == 0:
        print(f"  [Phase 2] Il faut au minimum {num_slots} stacks "
              f"(fournis : {len(ingot_slots)}).\n")
        return 0

    if leftover > 0:
        print(f"  [Phase 2] {leftover} stack(s) ignore(s).\n")

    single_pass = (total_cycles is not None and total_cycles < 0)
    is_infinite = (total_cycles == 0)
    if single_pass:
        print(f"  [Phase 2] Passage de {cycles_per_pass} cycle(s).\n")
    elif is_infinite:
        print(f"  [Phase 2] Boucle infinie ({cycles_per_pass} cycles par passage).")
        print(f"  Pause de {RESUPPLY_PAUSE}s entre chaque passage.\n")
    else:
        print(f"  [Phase 2] {total_cycles} cycle(s) a executer.\n")

    items_per_cycle = 64
    total_crafted = 0
    cycle_done = 0
    start_time = time.time()
    pass_number = 0

    while True:
        pass_number += 1

        cycles_this_pass = cycles_per_pass
        if not is_infinite and not single_pass:
            remaining = total_cycles - cycle_done
            if remaining <= 0:
                break
            cycles_this_pass = min(cycles_per_pass, remaining)

        for c in range(cycles_this_pass):
            cycle_done += 1
            cycle_slots = ingot_slots[c * num_slots : (c + 1) * num_slots]

            # Timer
            elapsed = time.time() - start_time
            if is_infinite or single_pass:
                timer_str = (f"| {format_duration(elapsed)} ecoule "
                             f"| {total_crafted} items craftes")
            else:
                if cycle_done > 1:
                    avg = elapsed / (cycle_done - 1)
                    remaining_time = avg * (total_cycles - cycle_done + 1)
                    timer_str = (f"| {format_duration(elapsed)} ecoule "
                                 f"| ~{format_duration(remaining_time)} restant")
                else:
                    timer_str = f"| {format_duration(elapsed)} ecoule"

            print(f"  [Phase 2] Cycle {cycle_done}"
                  f"{'/' + str(total_cycles) if (not is_infinite and not single_pass) else ''} "
                  f"({recipe['name']}) {timer_str}")

            # Remplir la grille
            for i, inv_slot in enumerate(cycle_slots):
                slot_pos = inv_pos(positions, inv_slot)
                craft_x, craft_y = positions[pattern[i]]
                safe_click(slot_pos[0], slot_pos[1])
                safe_click(craft_x, craft_y)

            # Recuperer les items
            ox, oy = output
            dx, dy = positions["drop_zone"]

            if stack_size == 1:
                for _ in range(items_per_cycle):
                    safe_click(ox, oy, delay=TIMINGS["craft_output_delay"])
                    safe_click(dx, dy, delay=TIMINGS["drop_delay"])
            else:
                num_stacks = items_per_cycle // stack_size
                reste = items_per_cycle % stack_size
                for _ in range(num_stacks):
                    for _ in range(stack_size):
                        safe_click(ox, oy, delay=TIMINGS["craft_output_delay"])
                    safe_click(dx, dy, delay=TIMINGS["drop_delay"])
                if reste > 0:
                    for _ in range(reste):
                        safe_click(ox, oy, delay=TIMINGS["craft_output_delay"])
                    safe_click(dx, dy, delay=TIMINGS["drop_delay"])

            total_crafted += items_per_cycle

        # Fin du passage
        if single_pass:
            break
        if not is_infinite:
            if cycle_done >= total_cycles:
                break
        else:
            # Pause reapprovisionnement
            elapsed = time.time() - start_time
            print(f"\n  Passage {pass_number} termine ({total_crafted} items, "
                  f"{format_duration(elapsed)}).")
            print(f"  Reapprovisionnement : {RESUPPLY_PAUSE}s...\n")
            for i in range(RESUPPLY_PAUSE, 0, -1):
                check_stop()
                if i % 10 == 0 or i <= 5:
                    print(f"  {i}s...")
                time.sleep(1)
            print("  Reprise !\n")

    elapsed = time.time() - start_time
    print(f"  [Phase 2] Termine : {total_crafted} {recipe['name']}(s) "
          f"en {format_duration(elapsed)}.\n")
    return total_crafted


def full_auto(positions, recipe, p1_slots_str=None, p1_stack=64,
              p2_slots_str=None, total_cycles=None):
    """Mode complet avec saisie interactive ou parametres directs."""
    print("\n" + "=" * 50)
    print(f"  MODE COMPLET : BLOCS -> {recipe['name'].upper()}")
    print("=" * 50)

    if p1_slots_str is None:
        print("\n  Slots : 0-26 (inventaire) | 27-35 (hotbar)\n")
        p1_slots_str = input("  Slots des blocs (ex: 0-2) : ").strip()
        s = input("  Taille stack [64] : ").strip()
        p1_stack = int(s) if s else 64

    block_slots = parse_slots(p1_slots_str)

    if p2_slots_str is None:
        num_s = len(recipe["pattern"])
        print(f"\n  Il faut {num_s} stacks par cycle.")
        p2_slots_str = input("  Slots des lingots : ").strip()

    ingot_slots = parse_slots(p2_slots_str)

    if total_cycles is None:
        c = input("  Nombre de cycles (0=infini) [1] : ").strip()
        total_cycles = int(c) if c else 1

    is_infinite = (total_cycles == 0)
    start_time = time.time()
    pass_number = 0

    while True:
        pass_number += 1

        countdown()
        phase_blocks_to_ingots(positions, block_slots, p1_stack)
        phase_craft(positions, recipe, ingot_slots,
                    total_cycles=-1 if is_infinite else total_cycles)

        if not is_infinite:
            break

        elapsed = time.time() - start_time
        print(f"\n  Passage complet {pass_number} termine ({format_duration(elapsed)}).")
        print(f"  Reapprovisionnement blocs : {RESUPPLY_PAUSE}s...\n")
        for i in range(RESUPPLY_PAUSE, 0, -1):
            check_stop()
            if i % 10 == 0 or i <= 5:
                print(f"  {i}s...")
            time.sleep(1)
        print("  Reprise !\n")

    elapsed = time.time() - start_time
    print(f"  Termine en {format_duration(elapsed)}.\n")

    # Retourne les parametres utilises (pour sauvegarder en preset)
    return {
        "p1_slots_str": p1_slots_str,
        "p1_stack": p1_stack,
        "p2_slots_str": p2_slots_str,
        "total_cycles": total_cycles,
    }


###########################################################
#  EXECUTION DE PRESET
###########################################################

def run_preset(config, preset_name, preset):
    """Execute un preset."""
    map_name = preset.get("map")
    if not map_name:
        print("  Preset sans map.\n")
        return

    positions = get_map_by_name(config, map_name)
    if not positions:
        print(f"  Map '{map_name}' introuvable.\n")
        return

    mode = preset.get("mode", "phase2")
    recipe_name = preset.get("recipe")
    recipe = None
    if recipe_name:
        recipe = find_recipe_by_name(recipe_name)
        if not recipe:
            print(f"  Recette '{recipe_name}' introuvable.\n")
            return

    cycles = preset.get("cycles") or 1

    print(f"\n  Preset : {preset_name}")
    print(f"  Map : {map_name} | Mode : {mode} | Cycles : {'infini' if cycles == 0 else cycles}")
    if recipe:
        print(f"  Recette : {recipe['name']}")
    print()

    try:
        start_stop_listener()
        set_gui_ref(positions)

        if mode == "phase1":
            slots = parse_slots(preset.get("phase1_slots", ""))
            stack = preset.get("phase1_stack_size") or 64
            countdown()
            phase_blocks_to_ingots(positions, slots, stack)

        elif mode == "phase2":
            slots = parse_slots(preset.get("phase2_slots", ""))
            countdown()
            phase_craft(positions, recipe, slots, total_cycles=cycles)

        elif mode == "complet":
            full_auto(positions, recipe,
                      p1_slots_str=preset.get("phase1_slots"),
                      p1_stack=preset.get("phase1_stack_size") or 64,
                      p2_slots_str=preset.get("phase2_slots"),
                      total_cycles=cycles)

    except StopException:
        print("  Arret propre.\n")
    finally:
        clear_gui_ref()


###########################################################
#  MENUS
###########################################################

def menu_parametres(config, positions):
    while True:
        active_name = config.get("active_map", "") if config else ""
        display = "aucune"
        if active_name and config:
            active_map = config["maps"].get(active_name)
            display = map_display_name(active_name, active_map, config)

        print("--- PARAMETRES ---\n")
        print(f"  1. Calibration (nouvelle map)")
        print(f"  2. Gerer les maps [{display}]")
        print(f"  3. Test de calibration")
        print(f"  4. Modifier les timings")
        print(f"  5. Gerer les presets")
        print(f"  0. Retour\n")

        choice = input("Ton choix : ").strip()

        if choice == "0":
            return config, positions
        elif choice == "1":
            config = calibrate(config)
            config, positions = load_config()
        elif choice == "2":
            config = manage_maps(config)
            config, positions = load_config()
        elif choice == "3":
            pos = get_active_map_or_warn(config)
            if pos:
                test_calibration(pos)
        elif choice == "4":
            config = edit_timings(config)
        elif choice == "5":
            manage_presets()
        else:
            print("Invalide.\n")


def menu_crafts(config, positions):
    while True:
        print("--- CRAFTS ---\n")
        print(f"  1. Phase 1 (Blocs -> Lingots)")
        print(f"  2. Phase 2 (Lingots -> Craft)")
        print(f"  3. Mode complet (Blocs -> Craft)")
        print(f"  4. Lancer un preset")
        print(f"  0. Retour\n")

        choice = input("Ton choix : ").strip()

        if choice == "0":
            return

        elif choice == "1":
            pos = get_active_map_or_warn(config)
            if not pos:
                continue
            print("\n  Inventaire : 0-26 | Hotbar : 27-35\n")
            slots_str = input("  Slots des blocs : ")
            block_slots = parse_slots(slots_str)
            s = input("  Taille stack [64] : ").strip()
            stack_size = int(s) if s else 64
            countdown()
            try:
                start_stop_listener()
                set_gui_ref(pos)
                phase_blocks_to_ingots(pos, block_slots, stack_size)
                propose_save_preset(config, "phase1",
                                    p1_slots_str=slots_str, p1_stack=stack_size)
            except StopException:
                print("  Arret propre.\n")
            finally:
                clear_gui_ref()

        elif choice == "2":
            pos = get_active_map_or_warn(config)
            if not pos:
                continue
            recipe = choose_recipe()
            if not recipe:
                continue
            num_s = len(recipe["pattern"])
            print(f"  Il faut {num_s} stacks par cycle.")
            slots_str = input("  Slots des materiaux : ")
            ingot_slots = parse_slots(slots_str)
            c = input("  Cycles (0=infini) [1] : ").strip()
            cycles = int(c) if c else 1
            countdown()
            try:
                start_stop_listener()
                set_gui_ref(pos)
                phase_craft(pos, recipe, ingot_slots, total_cycles=cycles)
                propose_save_preset(config, "phase2", recipe=recipe,
                                    p2_slots_str=slots_str, cycles=cycles)
            except StopException:
                print("  Arret propre.\n")
            finally:
                clear_gui_ref()

        elif choice == "3":
            pos = get_active_map_or_warn(config)
            if not pos:
                continue
            recipe = choose_recipe()
            if not recipe:
                continue
            try:
                start_stop_listener()
                set_gui_ref(pos)
                params = full_auto(pos, recipe)
                if params:
                    propose_save_preset(config, "complet", recipe=recipe,
                                        p1_slots_str=params["p1_slots_str"],
                                        p1_stack=params["p1_stack"],
                                        p2_slots_str=params["p2_slots_str"],
                                        cycles=params["total_cycles"])
            except StopException:
                print("  Arret propre.\n")
            finally:
                clear_gui_ref()

        elif choice == "4":
            name, preset = choose_preset()
            if name and preset:
                run_preset(config, name, preset)

        else:
            print("Invalide.\n")


###########################################################
#  LIGNE DE COMMANDE
###########################################################

def build_parser():
    """Construit le parser d'arguments."""
    parser = argparse.ArgumentParser(
        description="Minecraft Auto-Crafter",
        add_help=True,
    )
    sub = parser.add_subparsers(dest="command")

    # preset
    p_preset = sub.add_parser("preset", help="Lancer un preset")
    p_preset.add_argument("name", help="Nom du preset")

    # list-presets
    sub.add_parser("list-presets", help="Lister les presets")

    # phase1
    p_p1 = sub.add_parser("phase1", help="Phase 1 : blocs vers lingots")
    p_p1.add_argument("--map", help="Nom de la map")
    p_p1.add_argument("--slots", required=True, help="Slots des blocs (ex: 0-2)")
    p_p1.add_argument("--stack", type=int, default=64, help="Taille stack (defaut 64)")

    # phase2
    p_p2 = sub.add_parser("phase2", help="Phase 2 : lingots vers craft")
    p_p2.add_argument("--map", help="Nom de la map")
    p_p2.add_argument("--recipe", required=True, help="Nom de la recette")
    p_p2.add_argument("--slots", required=True, help="Slots materiaux (ex: 0-7)")
    p_p2.add_argument("--cycles", type=int, default=1, help="Cycles (0=infini, defaut 1)")

    # complet
    p_co = sub.add_parser("complet", help="Mode complet")
    p_co.add_argument("--map", help="Nom de la map")
    p_co.add_argument("--recipe", required=True, help="Nom de la recette")
    p_co.add_argument("--p1slots", required=True, help="Slots blocs phase1")
    p_co.add_argument("--p2slots", required=True, help="Slots lingots phase2")
    p_co.add_argument("--stack", type=int, default=64, help="Taille stack phase1")
    p_co.add_argument("--cycles", type=int, default=1, help="Cycles (0=infini)")

    return parser


def run_cli(args):
    """Execute une commande CLI."""
    config, _ = load_config()

    if args.command == "list-presets":
        presets = load_presets()
        if not presets:
            print("  Aucun preset.")
        for name, p in presets.items():
            desc = p.get("description") or ""
            print(f"  {name} [{p.get('mode')}] {p.get('recipe') or ''} : {desc}")
        return

    if args.command == "preset":
        presets = load_presets()
        if args.name not in presets:
            print(f"  Preset '{args.name}' introuvable.")
            return
        if config is None:
            print("  Aucune config.")
            return
        run_preset(config, args.name, presets[args.name])
        return

    if config is None:
        print("  Aucune config. Lance le menu interactif pour calibrer.")
        return

    # Resoudre la map
    map_name = args.map or config.get("active_map", "")
    positions = get_map_by_name(config, map_name)
    if not positions:
        print(f"  Map '{map_name}' introuvable.")
        return

    try:
        start_stop_listener()
        set_gui_ref(positions)

        if args.command == "phase1":
            slots = parse_slots(args.slots)
            countdown()
            phase_blocks_to_ingots(positions, slots, args.stack)

        elif args.command == "phase2":
            recipe = find_recipe_by_name(args.recipe)
            if not recipe:
                print(f"  Recette '{args.recipe}' introuvable.")
                return
            slots = parse_slots(args.slots)
            countdown()
            phase_craft(positions, recipe, slots, total_cycles=args.cycles)

        elif args.command == "complet":
            recipe = find_recipe_by_name(args.recipe)
            if not recipe:
                print(f"  Recette '{args.recipe}' introuvable.")
                return
            full_auto(positions, recipe,
                      p1_slots_str=args.p1slots, p1_stack=args.stack,
                      p2_slots_str=args.p2slots, total_cycles=args.cycles)

    except StopException:
        print("  Arret propre.\n")
    finally:
        clear_gui_ref()


###########################################################
#  POINT D'ENTREE
###########################################################

def main():
    print()
    print("=" * 50)
    print("  MINECRAFT AUTO-CRAFTER")
    print("=" * 50)
    print(f"\n  Plateforme : {CURRENT_PLATFORM}")
    print("  Touche M = arret immediat\n")

    config, positions = load_config()

    while True:
        print("Menu principal :")
        print(f"  1. Parametres")
        print(f"  2. Crafts")
        print(f"  0. Quitter\n")

        choice = input("Ton choix : ").strip()

        if choice == "0":
            print("A plus !")
            break
        elif choice == "1":
            config, positions = menu_parametres(config, positions)
        elif choice == "2":
            menu_crafts(config, positions)
        else:
            print("Invalide.\n")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        parser = build_parser()
        args = parser.parse_args()
        if args.command:
            run_cli(args)
        else:
            parser.print_help()
    else:
        main()