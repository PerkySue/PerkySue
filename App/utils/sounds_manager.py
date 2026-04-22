"""
Gestionnaire audio et skins pour PerkySue v19.
Supporte skins built-in (Default) et Pro (Data/Skins/).
"""

import logging
import random
import json
from pathlib import Path
from typing import Optional, List, Dict
import re

# Essayer d'importer pygame pour la lecture audio
try:
    import pygame.mixer as mixer
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False
    try:
        import winsound
    except ImportError:
        winsound = None

logger = logging.getLogger("perkysue.sounds")

try:
    from utils.skin_paths import normalize_skin_id, resolve_locale_skin_dir
except ImportError:
    from App.utils.skin_paths import normalize_skin_id, resolve_locale_skin_dir


class SoundManager:
    """Gestionnaire audio et skins pour PerkySue."""
    
    # Types d'événements audio
    EVENT_TYPES = ["stt_start", "stt_stop", "llm_start", "llm_stop"]

    def get_no_llm_message(self) -> str:
        """
        Retourne un message 'pas de LLM' qui correspond au personnage du skin.
        """
        # Messages par skin
        messages = {
            "sue": "Someone forgot to install my thinking module. I can listen, but I can't think!",
            "mike": "Yo, my brain's not plugged in! I can hear you but I can't process, dude.",
            "default": "No LLM detected. Skipping the [Improve] step.",
        }
        
        # Canonique ``Character/Locale`` → clé personnage = premier segment.
        ns = normalize_skin_id(self.paths, self.skin)
        skin_key = (
            ns.split("/", 1)[0].strip().lower()
            if "/" in ns
            else (ns.strip().lower() if ns else "default")
        )
        return messages.get(skin_key, messages["default"])
    
    def __init__(self, paths, skin: str = "Default", volume: float = 1.0):
        """
        Initialise le gestionnaire audio.
        
        Args:
            paths: Objet Paths (contient app_dir et data)
            skin: Nom du skin ("Default", "Sue", "Mike", ou custom)
            volume: Volume global (0.0 à 1.0)
        """
        self.paths = paths
        self.skin = skin
        self.volume = max(0.0, min(1.0, volume))
        self._sound_cache = {}
        self._moods_cache = {}
        self._last_played = {}  # event_type -> Path, évite répétition immédiate
        
        # Default skin audios — always available as per-event fallback
        self._default_audios_dir = self.paths.app_dir / "Skin" / "Default" / "audios"
        
        # Déterminer le dossier du skin
        self.skin_dir = self._resolve_skin_dir()
        self.audios_dir = self.skin_dir / "audios" if self.skin_dir else None
        self.images_dir = self.skin_dir / "images" if self.skin_dir else None
        
        logger.info(f"SoundManager: skin='{self.skin}', dir={self.skin_dir}")
        
        # Initialiser pygame si disponible
        if PYGAME_AVAILABLE and self.skin != "none":
            try:
                mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
                # pygame.mixer has no global set_volume; apply per-sound volume at play time.
                logger.info(f"Audio initialized (pygame)")
            except Exception as e:
                logger.warning(f"Could not initialize pygame audio: {e}")
        
        # Scanner les sons disponibles
        self._scan_sounds()
        
        # 🔥 WARNING: Check if we have MP3 files but no pygame
        self._check_mp3_without_pygame()
        
        # Charger les moods si présents
        self._load_moods()
    
    def _check_mp3_without_pygame(self):
        """Log visible warning if MP3 files exist but pygame is not available."""
        if PYGAME_AVAILABLE:
            return
            
        # Check if any configured sounds are MP3
        mp3_count = 0
        for event_type, files in self._available_sounds.items():
            for f in files:
                if f.suffix.lower() == '.mp3':
                    mp3_count += 1
        
        if mp3_count > 0:
            logger.warning("=" * 60)
            logger.warning("PYGAME NOT INSTALLED — CANNOT PLAY MP3 FILES!")
            logger.warning("Found %d MP3 sound(s) that will not play.", mp3_count)
            logger.warning("")
            logger.warning("SOLUTION: Install pygame with this command:")
            logger.warning("  %s\\Scripts\\pip.exe install pygame", self.paths.app_dir)
            logger.warning("=" * 60)
        else:
            logger.info("Pygame not available, but no MP3 files detected (WAV should work with winsound)")
    
    def _resolve_skin_dir(self) -> Optional[Path]:
        """
        Dossier du skin : ``Data/Skins/<Character>/<Locale>/`` (ou ancien ordre), ou ``Skins/<Name>/`` nu.
        """
        if not self.skin or self.skin == "Default":
            default_skin = self.paths.app_dir / "Skin" / "Default"
            return default_skin if default_skin.exists() else None
        ns = normalize_skin_id(self.paths, self.skin)
        resolved = resolve_locale_skin_dir(self.paths, ns)
        if resolved is not None:
            return resolved
        if "/" in ns:
            char, _loc = ns.split("/", 1)
            flat = self.paths.data / "Skins" / char.strip()
            if flat.is_dir():
                return flat
        else:
            user_skin = self.paths.data / "Skins" / self.skin.strip()
            if user_skin.is_dir():
                return user_skin
        default_skin = self.paths.app_dir / "Skin" / "Default"
        if default_skin.exists():
            logger.warning(f"Skin '{self.skin}' folder not found, using Default directory")
            return default_skin
        logger.error("No skin directory found!")
        return None
    
    def _scan_sounds(self):
        """
        Scanne les fichiers audio disponibles pour chaque event.
        Utilise rglob (récursif) pour inclure les fichiers dans les sous-dossiers.
        Per-event fallback: if configured skin has no files for an event,
        uses App/Skin/Default/audios/{event}/ instead.
        """
        self._available_sounds = {}
        audio_extensions = ['.mp3', '.wav', '.ogg', '.flac', '.m4a']
        
        for event_type in self.EVENT_TYPES:
            files = []
            source = None
            
            # 1. Try configured skin's audio folder (rglob = inclut sous-dossiers)
            if self.audios_dir:
                sound_dir = self.audios_dir / event_type
                if sound_dir.exists():
                    for ext in audio_extensions:
                        files.extend(sound_dir.rglob(f"*{ext}"))
                    if files:
                        source = "skin"
            
            # 2. Per-event fallback to Default if no files found
            if not files and self._default_audios_dir:
                fallback_dir = self._default_audios_dir / event_type
                if fallback_dir.exists():
                    for ext in audio_extensions:
                        files.extend(fallback_dir.rglob(f"*{ext}"))
                    if files:
                        source = "default-fallback"
            
            files = sorted(set(files))  # déduplique au cas où (même fichier via chemins différents)
            self._available_sounds[event_type] = files
            
            if files and source == "default-fallback":
                logger.info(f"Skin '{self.skin}' has no {event_type} sounds — using Default fallback ({len(files)} file(s))")
            elif files:
                logger.info(f"Found {len(files)} sound(s) for {self.skin}/{event_type}")
    
    def _load_moods(self):
        """Charge le fichier moods.json du skin si présent."""
        if not self.images_dir:
            return
            
        moods_file = self.images_dir / "moods.json"
        if moods_file.exists():
            try:
                with open(moods_file, 'r', encoding='utf-8') as f:
                    self._moods_cache = json.load(f)
                logger.info(f"Loaded {len(self._moods_cache)} moods for {self.skin}")
            except Exception as e:
                logger.warning(f"Could not load moods.json: {e}")
    
    def play(self, event_type: str) -> bool:
        """
        Joue un son pour l'événement donné.
        
        Args:
            event_type: stt_start, stt_stop, llm_start, llm_stop
        
        Returns:
            True si le son a été joué
        """
        if self.skin == "none":
            return False
        
        if event_type not in self.EVENT_TYPES:
            logger.warning(f"Unknown sound event: {event_type}")
            return False
        
        available = self._available_sounds.get(event_type, [])
        
        if not available:
            logger.debug(f"No sounds available for {event_type}")
            return False
        
        # Sélection aléatoire — évite le dernier joué si possible (2+ fichiers)
        last = self._last_played.get(event_type)
        candidates = [f for f in available if f != last] if last and len(available) > 1 else available
        sound_file = random.choice(candidates)
        self._last_played[event_type] = sound_file
        
        try:
            return self._play_file(sound_file)
        except Exception as e:
            logger.error(f"Failed to play sound {sound_file}: {e}")
            return False
    
    def _play_file(self, sound_file: Path) -> bool:
        """Joue un fichier audio."""
        logger.debug(f"Playing sound: {sound_file.name}")
        
        if PYGAME_AVAILABLE:
            try:
                if sound_file not in self._sound_cache:
                    self._sound_cache[sound_file] = mixer.Sound(str(sound_file))
                snd = self._sound_cache[sound_file]
                try:
                    snd.set_volume(self.volume)
                except Exception:
                    pass
                snd.play()
                return True
            except Exception as e:
                logger.warning(f"Pygame playback failed: {e}")
        
        # Fallback winsound (Windows, WAV uniquement)
        if winsound:
            if sound_file.suffix.lower() == '.wav':
                try:
                    winsound.PlaySound(str(sound_file), winsound.SND_ASYNC | winsound.SND_FILENAME)
                    return True
                except Exception as e:
                    logger.error(f"Winsound playback failed: {e}")
            else:
                # 🔥 Log explicite pour le prochain dev
                logger.error(f"Cannot play {sound_file.suffix} file without pygame: {sound_file.name}")
        
        return False
    
    def get_mood_image(self, llm_output: str) -> Optional[str]:
        """
        Extrait le mood du texte LLM et retourne l'image correspondante.
        
        Args:
            llm_output: Texte généré par le LLM (peut contenir [MOOD: xxx])
        
        Returns:
            Nom du fichier image ou None
        """
        if not self._moods_cache:
            return None
        
        # Chercher la balise [MOOD: xxx]
        match = re.search(r"\[MOOD:\s*(\w+)\]", llm_output, re.IGNORECASE)
        if not match:
            return None
        
        mood_key = match.group(1).lower()
        
        # Lookup direct
        if mood_key in self._moods_cache:
            return self._moods_cache[mood_key].get("file")
        
        # Lookup par keywords
        for key, data in self._moods_cache.items():
            keywords = data.get("keywords", [])
            if mood_key in [k.lower() for k in keywords]:
                return data.get("file")
        
        return None
    
    def strip_mood_tag(self, llm_output: str) -> str:
        """Retire la balise [MOOD: xxx] du texte."""
        return re.sub(r"\s*\[MOOD:\s*\w+\]\s*", " ", llm_output).strip()
    
    def get_image_path(self, image_name: str) -> Optional[Path]:
        """
        Retourne le chemin d'une image du skin.
        
        Args:
            image_name: "icon.png", "tray_icon.png", "hero.png", etc.
        """
        if not self.images_dir:
            return None
        
        img_path = self.images_dir / image_name
        return img_path if img_path.exists() else None
    
    def list_available_skins(self) -> List[str]:
        """Liste tous les skins disponibles."""
        skins = ["Default"]  # Toujours présent
        
        # Skins Pro dans Data/Skins/
        pro_skins_dir = self.paths.data / "Skins"
        if pro_skins_dir.exists():
            for folder in pro_skins_dir.iterdir():
                if folder.is_dir() and (folder / "audios").exists():
                    skins.append(folder.name)
        
        return skins
    
    # Méthodes de convenance
    def play_stt_start(self) -> bool:
        return self.play("stt_start")
    
    def play_stt_stop(self) -> bool:
        return self.play("stt_stop")

    def play_stt_stop_default_skin(self) -> bool:
        """Joue stt_stop depuis App/Skin/Default/audios uniquement (ex. bouton Run Test)."""
        if not self._default_audios_dir:
            return False
        sound_dir = self._default_audios_dir / "stt_stop"
        if not sound_dir.exists():
            return False
        for ext in [".mp3", ".wav", ".ogg", ".flac", ".m4a"]:
            files = sorted(sound_dir.glob(f"*{ext}"))
            if files:
                try:
                    return self._play_file(files[0])
                except Exception as e:
                    logger.warning("play_stt_stop_default_skin: %s", e)
        return False

    def play_llm_start(self) -> bool:
        return self.play("llm_start")
    
    def play_llm_stop(self) -> bool:
        return self.play("llm_stop")
    
    def set_skin(self, skin: str):
        """Change de skin (recharge tout). Per-event fallback to Default is automatic."""
        self.skin = skin
        self._sound_cache.clear()
        self._last_played.clear()
        self.skin_dir = self._resolve_skin_dir()
        self.audios_dir = self.skin_dir / "audios" if self.skin_dir else None
        self.images_dir = self.skin_dir / "images" if self.skin_dir else None
        self._default_audios_dir = self.paths.app_dir / "Skin" / "Default" / "audios"
        self._scan_sounds()
        self._load_moods()
    
    def set_volume(self, volume: float):
        """Change le volume."""
        self.volume = max(0.0, min(1.0, volume))
        if PYGAME_AVAILABLE:
            for snd in self._sound_cache.values():
                try:
                    snd.set_volume(self.volume)
                except Exception:
                    pass

    def play_system_sound(self, sound_name: str) -> bool:
        """
        Joue un son système depuis le dossier system/.
        Falls back to Default skin if configured skin has no system sounds.
        
        Args:
            sound_name: nom du fichier sans extension (ex: "no_llm", "llm_incompatible")
        """
        audio_extensions = ['.mp3', '.wav', '.ogg', '.flac']
        
        # Try configured skin first, then Default fallback
        dirs_to_try = []
        if self.audios_dir:
            dirs_to_try.append(self.audios_dir / "system")
        if self._default_audios_dir:
            dirs_to_try.append(self._default_audios_dir / "system")
        
        for system_dir in dirs_to_try:
            if not system_dir.exists():
                continue
            for ext in audio_extensions:
                sound_file = system_dir / f"{sound_name}{ext}"
                if sound_file.exists():
                    return self._play_file(sound_file)
        
        logger.debug(f"System sound not found: {sound_name}")
        return False