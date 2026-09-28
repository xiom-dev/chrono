"""Chrono — chronomètre et compte à rebours, aux couleurs de ZyRoom.

La version Windows, pour la guilde : Python + tkinter, la boîte à outils
graphique livrée avec Python lui-même. Mêmes textes, mêmes couleurs, mêmes
fonctions que la version GTK de Linux.

Deux modes, choisis en haut de la fenêtre :

* **Compte à rebours** : on règle heures, minutes et secondes — au clavier,
  ou à la molette de la souris posée sur le champ —, puis « Lancer ». Au bout,
  le son choisi dans les options est joué **une seule fois**.
* **Chronomètre** : « Lancer » part (ou repart), « Arrêter » fige le temps,
  « Remise à zéro » l'efface.

« Arrêter » coupe le décompte **et** le son s'il joue. La dernière durée
lancée est mémorisée : à la réouverture, « Lancer » suffit.

Sous Windows, le son se lit par `winsound`, intégré à Python : fichiers
**.wav** seulement. Le fichier `launch.wav`, posé à côté de celui-ci, est le
son proposé d'office.

Lancer : double-clic sur Chrono.pyw (Python installé depuis python.org).
"""
import json
import os
import subprocess
import sys
import time
import tkinter as tk
from tkinter import filedialog

WINDOWS = sys.platform.startswith("win")
if WINDOWS:
    import winsound

# Les couleurs de ZyRoom : fond ardoise, texte gris clair, jaune "or" pour le
# temps, vert sarcelle pour l'action, rouge pour l'arret.
FOND = "#10171a"
SURFACE = "#172226"
VARIANTE = "#1e2c31"
TEXTE = "#e2e8e6"
FAIBLE = "#bcc8c6"
SARCELLE = "#3f7a68"
SARCELLE_CLAIR = "#7fb3a2"
OR = "#e8c15a"
ROUGE = "#e2696a"
ETEINT = "#5d6b69"

POLICE = "Segoe UI" if WINDOWS else "Cantarell"
# Les symboles des boutons (lecture, pause, arret) : "Segoe UI Symbol" les a
# tous sous Windows, la ou "Segoe UI" n'a pas celui de la pause.
POLICE_SYMBOLES = "Segoe UI Symbol" if WINDOWS else "DejaVu Sans"

ICI = os.path.dirname(os.path.abspath(__file__))
# Le son de la guilde, livre avec l'appli.
SON_LIVRE = os.path.join(ICI, "launch.wav")

# Les sonneries du systeme : celles de Windows, ou de GNOME pour essayer
# l'appli sous Linux.
if WINDOWS:
    DOSSIERS_SONNERIES = (os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Media"),)
    EXTENSIONS_SON = (".wav",)
    REGLAGES = os.path.join(os.environ.get("APPDATA", ICI), "Chrono", "reglages.json")
else:
    DOSSIERS_SONNERIES = ("/usr/share/sounds/freedesktop/stereo",
                          "/usr/share/sounds/gnome/default/alerts")
    EXTENSIONS_SON = (".oga", ".ogg", ".wav", ".flac", ".opus")
    REGLAGES = os.path.join(os.path.expanduser("~/.config"), "chrono-tk", "reglages.json")


def lire_reglages() -> dict:
    try:
        with open(REGLAGES, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def ecrire_reglages(reglages: dict) -> None:
    try:
        os.makedirs(os.path.dirname(REGLAGES), exist_ok=True)
        with open(REGLAGES, "w", encoding="utf-8") as f:
            json.dump(reglages, f)
    except OSError:
        pass            # un reglage perdu ne doit pas bloquer le chrono


def en_texte(s: int) -> str:
    """Des secondes en HH:MM:SS."""
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def joli_nom(chemin: str) -> str:
    """« phone-incoming-call.oga » devient « phone incoming call »."""
    return os.path.splitext(os.path.basename(chemin))[0].replace("-", " ").replace("_", " ")


def sonneries(perso: list) -> list:
    """Le son livre avec l'appli en tete, puis les sons perso, puis ceux des
    dossiers de sonneries, tries par nom. Les voix de test des haut-parleurs
    n'ont rien d'une sonnerie."""
    trouves = []
    for dossier in DOSSIERS_SONNERIES:
        try:
            noms = os.listdir(dossier)
        except OSError:
            continue
        trouves += [os.path.join(dossier, n) for n in noms
                    if n.lower().endswith(EXTENSIONS_SON)
                    and not n.startswith("audio-channel-")]
    trouves.sort(key=lambda c: joli_nom(c).lower())
    livre = [SON_LIVRE] if os.path.isfile(SON_LIVRE) else []
    return livre + [c for c in perso if os.path.isfile(c) and c not in trouves] + trouves


class Son:
    """Joue un fichier une fois, et sait le couper."""

    def __init__(self) -> None:
        self.lecteur = None     # sous Linux, le processus pw-play en cours

    def jouer(self, chemin: str) -> None:
        self.couper()
        if WINDOWS:
            # SND_ASYNC : la fenetre reste vivante pendant le son. Sans sortie
            # son (casque debranche...), winsound leve une erreur : on se tait.
            try:
                winsound.PlaySound(chemin, winsound.SND_FILENAME | winsound.SND_ASYNC)
            except RuntimeError:
                pass
        else:
            try:
                self.lecteur = subprocess.Popen(["pw-play", chemin])
            except OSError:
                self.lecteur = None

    def couper(self) -> None:
        if WINDOWS:
            try:
                winsound.PlaySound(None, winsound.SND_PURGE)
            except RuntimeError:
                pass
        elif self.lecteur is not None:
            self.lecteur.terminate()
            self.lecteur = None


def bouton(parent, texte, action, fond=VARIANTE, encre=TEXTE, gras=False, **options):
    """Un bouton plat aux couleurs de l'appli, qui s'eclaire au survol."""
    b = tk.Button(parent, text=texte, command=action, bg=fond, fg=encre,
                  activebackground=SARCELLE_CLAIR if fond == VARIANTE else fond,
                  activeforeground=encre, disabledforeground=ETEINT,
                  relief="flat", bd=0, padx=16, pady=8, cursor="hand2",
                  highlightthickness=0,
                  font=(POLICE, 11, "bold" if gras else "normal"), **options)
    return b


class Bulle:
    """Le mot d'un bouton, montre au survol : tkinter n'a pas d'infobulle."""

    def __init__(self, widget, texte: str) -> None:
        self.widget, self.texte, self.fenetre = widget, texte, None
        widget.bind("<Enter>", self.montrer, add="+")
        widget.bind("<Leave>", self.cacher, add="+")
        widget.bind("<ButtonPress>", self.cacher, add="+")

    def montrer(self, _e=None) -> None:
        if self.fenetre:
            return
        x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2 - 20
        y = self.widget.winfo_rooty() - 30
        self.fenetre = tk.Toplevel(self.widget)
        self.fenetre.wm_overrideredirect(True)
        self.fenetre.geometry(f"+{x}+{y}")
        tk.Label(self.fenetre, text=self.texte, bg=SURFACE, fg=TEXTE, padx=8, pady=3,
                 font=(POLICE, 10), highlightthickness=1,
                 highlightbackground=VARIANTE).pack()

    def cacher(self, _e=None) -> None:
        if self.fenetre:
            self.fenetre.destroy()
            self.fenetre = None


class Chrono(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Chrono")
        self.configure(bg=FOND)
        self.geometry("560x400")
        self.minsize(520, 360)
        self.reglages = lire_reglages()
        self.son = Son()
        self.garder_perso(self.reglages.get("son", ""))

        # Le temps : l'horloge monotone, et un battement qui repeint -- comme
        # un setInterval en JavaScript.
        self.debut = 0.0
        self.duree = 0.0
        self.battement = None   # l'identifiant du battement, None a l'arret
        # Le temps deja ecoule avant une pause, dans les deux modes : pause le
        # fige, lecture repart de la, arret l'efface et ramene au debut.
        self.cumul = 0.0
        self.en_pause = False

        pile = tk.Frame(self, bg=FOND)
        pile.pack(fill="both", expand=True, padx=20, pady=20)

        # Les deux modes : deux boutons dont un seul reste allume.
        modes = tk.Frame(pile, bg=FOND)
        modes.pack(fill="x")
        self.mode = tk.StringVar(value="chrono" if self.reglages.get("mode") == "chrono"
                                 else "rebours")
        self.bouton_rebours = bouton(modes, "Compte à rebours", lambda: self.choisir_mode("rebours"))
        self.bouton_chrono = bouton(modes, "Chronomètre", lambda: self.choisir_mode("chrono"))
        self.bouton_rebours.pack(side="left")
        self.bouton_chrono.pack(side="left", padx=8)
        bouton(modes, "Options", self.ouvrir_options).pack(side="right")
        # La saisie en secondes, a portee de main entre les modes et les
        # options : une case, visible en compte a rebours seulement.
        self.var_secondes = tk.BooleanVar(value=self.en_secondes())
        self.case_secondes = tk.Checkbutton(
            modes, text="En secondes", variable=self.var_secondes,
            command=lambda: self.basculer_secondes(self.var_secondes.get()),
            bg=FOND, fg=TEXTE, selectcolor=SURFACE, activebackground=FOND,
            activeforeground=TEXTE, highlightthickness=0, bd=0, cursor="hand2",
            font=(POLICE, 11))

        # Les trois champs du compte a rebours, et le champ en secondes seules,
        # dans leur zone. **Enfants de la zone, et non poses dedans par
        # "in_".** Tk empile les fenetres dans l'ordre de creation : une zone
        # creee apres les champs passait par-dessus, et avalait la molette et
        # les clics.
        self.zone_champs = tk.Frame(pile, bg=FOND)
        self.champs = tk.Frame(self.zone_champs, bg=FOND)
        self.heures = self.champ(self.champs, 99, "h")
        self.minutes = self.champ(self.champs, 59, "min")
        self.secondes = self.champ(self.champs, 59, "s")
        self.champs_sec = tk.Frame(self.zone_champs, bg=FOND)
        self.en_sec = self.champ(self.champs_sec, 359999, "s", largeur=6, boucle=False)

        self.temps = tk.Label(pile, text="00:00:00", bg=FOND, fg=OR,
                              font=(POLICE, 48, "bold"))
        self.etat = tk.Label(pile, text="", bg=FOND, fg=FAIBLE, font=(POLICE, 11))

        boutons = tk.Frame(pile, bg=FOND)
        # Les trois boutons, avec les symboles des lecteurs : lancer ou
        # reprendre, pause, arret. Le mot reste au survol.
        self.lancer = bouton(boutons, "▶", self.demarrer, fond=SARCELLE, encre="#ffffff")
        self.pause = bouton(boutons, "❚❚", self.mettre_en_pause, encre=OR)
        self.arreter = bouton(boutons, "■", self.stopper, encre=ROUGE)
        for b, mot in ((self.lancer, "Lancer"), (self.pause, "Pause"), (self.arreter, "Arrêter")):
            b.configure(font=(POLICE_SYMBOLES, 16), pady=4)
            Bulle(b, mot)
        for i, b in enumerate((self.lancer, self.pause, self.arreter)):
            b.pack(side="left", fill="x", expand=True, padx=(0 if i == 0 else 12, 0))
        self.pause.configure(state="disabled")

        # L'ordre d'empilement : les boutons en bas d'abord, puis le reste.
        boutons.pack(side="bottom", fill="x")
        self.etat.pack(side="bottom", pady=(0, 8))
        self.zone_champs.pack(fill="x", pady=(14, 0))
        self.champs.pack(anchor="w")
        self.temps.pack(expand=True)

        self.poser_duree(int(self.reglages.get("derniere_duree", 0)))
        self.choisir_mode(self.mode.get())

    def champ(self, boite, maxi, unite, largeur=3, boucle=True) -> tk.Spinbox:
        champ = tk.Spinbox(boite, from_=0, to=maxi, wrap=boucle, width=largeur,
                           font=(POLICE, 22), justify="center",
                           bg=SURFACE, fg=OR, insertbackground=OR,
                           buttonbackground=VARIANTE, relief="flat",
                           highlightthickness=1, highlightbackground=VARIANTE,
                           highlightcolor=SARCELLE_CLAIR, disabledbackground=SURFACE,
                           command=self.peindre_repos)
        # Le clavier : des chiffres seulement.
        champ.configure(validate="key", validatecommand=(
            self.register(lambda v: v == "" or (v.isdigit() and int(v) <= maxi)), "%P"))
        champ.bind("<KeyRelease>", lambda _e: self.peindre_repos())
        # La molette posee dessus, sans clic : Windows donne un "delta",
        # Linux des boutons 4 et 5.
        champ.bind("<MouseWheel>", lambda e: self.tourner(champ, 1 if e.delta > 0 else -1))
        champ.bind("<Button-4>", lambda _e: self.tourner(champ, 1))
        champ.bind("<Button-5>", lambda _e: self.tourner(champ, -1))
        champ.pack(side="left", padx=(0, 6))
        tk.Label(boite, text=unite, bg=FOND, fg=FAIBLE, font=(POLICE, 11)).pack(side="left", padx=(0, 10))
        return champ

    def tourner(self, champ: tk.Spinbox, sens: int) -> str:
        if str(champ.cget("state")) != "disabled":
            champ.invoke("buttonup" if sens > 0 else "buttondown")
        return "break"

    # ------------------------------------------------------------ reglages
    def rebours(self) -> bool:
        return self.mode.get() == "rebours"

    def en_secondes(self) -> bool:
        return bool(self.reglages.get("en_secondes", False))

    def chemin_son(self) -> str:
        """Le son choisi ; vide dans les reglages veut dire « le son livre »."""
        chemin = self.reglages.get("son", "")
        if chemin and os.path.isfile(chemin):
            return chemin
        return SON_LIVRE if os.path.isfile(SON_LIVRE) else ""

    def garder_perso(self, chemin: str) -> None:
        """Un son pris hors des dossiers de sonneries rejoint la liste.

        **Le son livre n'y est jamais ecrit par son chemin.** L'exe autonome se
        deballe a chaque lancement dans un dossier temporaire different
        (``_MEI...``) : son chemin d'hier n'existe plus aujourd'hui."""
        perso = [c for c in self.reglages.get("sons_perso", [])
                 if c != SON_LIVRE and "_MEI" not in c]
        if (chemin and chemin != SON_LIVRE and os.path.isfile(chemin)
                and chemin not in perso and os.path.dirname(chemin) not in DOSSIERS_SONNERIES):
            perso.append(chemin)
        self.reglages["sons_perso"] = perso
        if "_MEI" in self.reglages.get("son", ""):
            self.reglages["son"] = ""
        ecrire_reglages(self.reglages)

    @staticmethod
    def valeur(champ: tk.Spinbox) -> int:
        texte = champ.get()
        return int(texte) if texte.isdigit() else 0

    @staticmethod
    def poser(champ: tk.Spinbox, valeur: int) -> None:
        etat = champ.cget("state")
        champ.configure(state="normal")
        champ.delete(0, "end")
        champ.insert(0, str(valeur))
        champ.configure(state=etat)

    def poser_duree(self, total: int) -> None:
        """Met une duree dans les deux saisies, h/min/s et secondes seules."""
        self.poser(self.heures, total // 3600)
        self.poser(self.minutes, total % 3600 // 60)
        self.poser(self.secondes, total % 60)
        self.poser(self.en_sec, total)

    def duree_des_champs(self) -> int:
        if self.en_secondes():
            return self.valeur(self.en_sec)
        return (self.valeur(self.heures) * 3600 + self.valeur(self.minutes) * 60
                + self.valeur(self.secondes))

    def basculer_secondes(self, oui: bool) -> None:
        """L'option : la duree deja reglee passe d'une saisie a l'autre."""
        total = self.duree_des_champs()
        self.reglages["en_secondes"] = oui
        ecrire_reglages(self.reglages)
        self.poser_duree(total)
        self.afficher_champs()

    def afficher_champs(self) -> None:
        self.champs.pack_forget()
        self.champs_sec.pack_forget()
        if self.rebours():
            (self.champs_sec if self.en_secondes() else self.champs).pack(anchor="w")
        # La case "En secondes" : en compte a rebours seulement, entre les
        # modes et "Options".
        if self.rebours():
            self.case_secondes.pack(side="left", padx=(8, 0))
        else:
            self.case_secondes.pack_forget()
        # Le mode allume : vert sarcelle ; l'autre, gris.
        for b, oui in ((self.bouton_rebours, self.rebours()), (self.bouton_chrono, not self.rebours())):
            b.configure(bg=SARCELLE if oui else VARIANTE, fg="#ffffff" if oui else TEXTE,
                        activebackground=SARCELLE if oui else SARCELLE_CLAIR)

    def champs_actifs(self, oui: bool) -> None:
        for champ in (self.heures, self.minutes, self.secondes, self.en_sec):
            champ.configure(state="normal" if oui else "disabled")

    # ------------------------------------------------------------ gestes
    def choisir_mode(self, mode: str) -> None:
        self.stopper()
        self.mode.set(mode)
        self.reglages["mode"] = mode
        ecrire_reglages(self.reglages)
        self.afficher_champs()
        self.peindre_repos()

    def peindre_repos(self) -> None:
        """L'affichage a l'arret : la duree reglee, ou zero en chronometre.
        En pause, le temps fige reste affiche."""
        if self.battement or self.en_pause:
            return
        self.temps.configure(text=en_texte(self.duree_des_champs()) if self.rebours()
                             else "00:00:00")

    def demarrer(self) -> None:
        """Lecture : lance, ou reprend apres une pause."""
        if self.battement:
            return
        self.son.couper()
        if self.en_pause:
            # La reprise : on repart du temps fige, sans relire les champs.
            self.en_pause = False
        elif self.rebours():
            total = self.duree_des_champs()
            if total == 0:
                self.etat.configure(text="Règle une durée d'abord.")
                return
            # Memorisee des le lancement : c'est elle qu'on veut retrouver.
            self.reglages["derniere_duree"] = total
            ecrire_reglages(self.reglages)
            self.duree = float(total)
            self.cumul = 0.0
        else:
            self.cumul = 0.0
        self.debut = time.monotonic() - self.cumul
        self.etat.configure(text="")
        self.lancer.configure(state="disabled")
        self.pause.configure(state="normal")
        self.champs_actifs(False)
        self.avancer()

    def mettre_en_pause(self) -> None:
        """Pause : fige le temps ; lecture le fera repartir de la."""
        if not self.battement:
            return
        self.cumul = time.monotonic() - self.debut
        self.after_cancel(self.battement)
        self.battement = None
        self.en_pause = True
        self.etat.configure(text="En pause")
        self.lancer.configure(state="normal")
        self.pause.configure(state="disabled")

    def stopper(self) -> None:
        """Arret : coupe le decompte et le son, et ramene au debut -- la duree
        reglee en compte a rebours, zero en chronometre."""
        if self.battement:
            self.after_cancel(self.battement)
            self.battement = None
        self.en_pause = False
        self.cumul = 0.0
        self.son.couper()
        self.lancer.configure(state="normal")
        self.pause.configure(state="disabled")
        self.champs_actifs(True)
        self.etat.configure(text="")
        self.peindre_repos()

    def avancer(self) -> None:
        """Un battement : repeint, puis se reprogramme dans 100 ms."""
        ecoule = time.monotonic() - self.debut
        if not self.rebours():
            # Le chronometre compte les secondes pleines, comme une montre.
            self.temps.configure(text=en_texte(int(ecoule)))
            self.battement = self.after(100, self.avancer)
            return
        reste = self.duree - ecoule
        if reste > 0:
            # Le compte a rebours arrondit vers le haut : 0,4 s restantes
            # s'affichent encore 00:00:01, et 00:00:00 veut dire "fini".
            self.temps.configure(text=en_texte(int(reste) + (reste % 1 > 0)))
            self.battement = self.after(100, self.avancer)
            return
        # Au bout : on s'arrete, on le dit, et le son part une fois.
        self.battement = None
        self.temps.configure(text="00:00:00")
        self.etat.configure(text="Terminé !")
        self.cumul = 0.0
        self.lancer.configure(state="normal")
        self.pause.configure(state="disabled")
        self.champs_actifs(True)
        self.jouer()

    def jouer(self, chemin: str = "") -> None:
        chemin = chemin or self.chemin_son()
        if not chemin:
            self.etat.configure(text=self.etat.cget("text") + " (aucun son choisi)")
            return
        self.son.jouer(chemin)

    # ------------------------------------------------------------ options
    def ouvrir_options(self) -> None:
        """Le choix du son joue au bout du compte a rebours."""
        fenetre = tk.Toplevel(self, bg=FOND)
        fenetre.title("Options")
        fenetre.geometry("460x560")
        fenetre.transient(self)
        fenetre.grab_set()
        pile = tk.Frame(fenetre, bg=FOND)
        pile.pack(fill="both", expand=True, padx=16, pady=16)
        tk.Label(pile, text="Son joué à la fin du compte à rebours :", bg=FOND, fg=TEXTE,
                 font=(POLICE, 11), anchor="w").pack(fill="x")
        nom = tk.Label(pile, bg=FOND, fg=FAIBLE, font=(POLICE, 11), anchor="w")
        nom.pack(fill="x", pady=(2, 8))

        # La liste des sonneries, qui defile : un clic sur la ligne la
        # choisit, le bouton lecture la fait entendre sans la choisir.
        cadre = tk.Frame(pile, bg=SURFACE)
        cadre.pack(fill="both", expand=True)
        toile = tk.Canvas(cadre, bg=SURFACE, highlightthickness=0)
        barre = tk.Scrollbar(cadre, orient="vertical", command=toile.yview)
        toile.configure(yscrollcommand=barre.set)
        barre.pack(side="right", fill="y")
        toile.pack(side="left", fill="both", expand=True)
        interieur = tk.Frame(toile, bg=SURFACE)
        fenetre_liste = toile.create_window((0, 0), window=interieur, anchor="nw")
        interieur.bind("<Configure>", lambda _e: toile.configure(scrollregion=toile.bbox("all")))
        toile.bind("<Configure>", lambda e: toile.itemconfigure(fenetre_liste, width=e.width))

        def defiler(sens):
            toile.yview_scroll(sens, "units")
            return "break"

        lignes = {}
        perso = self.reglages.get("sons_perso", [])

        def ajouter_ligne(chemin):
            ligne = tk.Frame(interieur, bg=SURFACE)
            ligne.pack(fill="x")
            etiquette = tk.Label(ligne, text=joli_nom(chemin), bg=SURFACE, fg=TEXTE,
                                 font=(POLICE, 11), anchor="w", padx=8, pady=4, cursor="hand2")
            etiquette.pack(side="left", fill="x", expand=True)
            morceaux = [ligne, etiquette]
            if chemin in perso or chemin == SON_LIVRE:
                marque = tk.Label(ligne, text="perso", bg=SURFACE, fg=FAIBLE, font=(POLICE, 10))
                marque.pack(side="left", padx=6)
                morceaux.append(marque)
            ecouter = tk.Button(ligne, text="▶", command=lambda: self.jouer(chemin),
                                bg=VARIANTE, fg=OR, activebackground=SARCELLE_CLAIR,
                                activeforeground=OR, relief="flat", bd=0, padx=10,
                                cursor="hand2", highlightthickness=0, font=(POLICE, 10))
            ecouter.pack(side="right", padx=6, pady=2)
            for m in morceaux:
                m.bind("<Button-1>", lambda _e: choisir(chemin))
            for m in morceaux + [ecouter]:
                m.bind("<MouseWheel>", lambda e: defiler(-1 if e.delta > 0 else 1))
                m.bind("<Button-4>", lambda _e: defiler(-1))
                m.bind("<Button-5>", lambda _e: defiler(1))
            lignes[chemin] = morceaux

        def choisir(chemin):
            # Le son livre s'ecrit "vide" : voir garder_perso.
            self.reglages["son"] = "" if chemin == SON_LIVRE else chemin
            ecrire_reglages(self.reglages)
            peindre()

        def peindre():
            chemin = self.chemin_son()
            nom.configure(text=joli_nom(chemin) if chemin else "aucun son choisi")
            # La sonnerie en cours reste surlignee dans la liste.
            for c, morceaux in lignes.items():
                fond, encre = (SARCELLE, "#ffffff") if c == chemin else (SURFACE, TEXTE)
                for m in morceaux:
                    m.configure(bg=fond)
                morceaux[1].configure(fg=encre)

        for chemin in sonneries(perso):
            ajouter_ligne(chemin)
        toile.bind("<MouseWheel>", lambda e: defiler(-1 if e.delta > 0 else 1))
        toile.bind("<Button-4>", lambda _e: defiler(-1))
        toile.bind("<Button-5>", lambda _e: defiler(1))

        def autre_fichier():
            chemin = filedialog.askopenfilename(
                parent=fenetre, title="Choisir un son",
                initialdir=DOSSIERS_SONNERIES[0] if os.path.isdir(DOSSIERS_SONNERIES[0]) else ICI,
                filetypes=[("Sons", " ".join("*" + e for e in EXTENSIONS_SON))])
            if not chemin:
                return
            chemin = os.path.normpath(chemin)
            self.garder_perso(chemin)
            if chemin not in lignes:
                # Nouveau son perso : la liste est refaite, il y entre en tete.
                for morceaux in lignes.values():
                    morceaux[0].destroy()
                lignes.clear()
                for c in sonneries(self.reglages.get("sons_perso", [])):
                    ajouter_ligne(c)
            choisir(chemin)

        rangee = tk.Frame(pile, bg=FOND)
        rangee.pack(fill="x", pady=(10, 0))
        for i, (texte, action) in enumerate((("Autre fichier…", autre_fichier),
                                             ("Écouter", self.jouer),
                                             ("Couper", self.son.couper))):
            bouton(rangee, texte, action).pack(side="left", fill="x", expand=True,
                                               padx=(0 if i == 0 else 8, 0))
        bouton(pile, "Fermer", fenetre.destroy).pack(anchor="e", pady=(10, 0))
        peindre()


def main() -> None:
    if WINDOWS:
        # Net sur les ecrans agrandis a 125 ou 150 % : sans cela, Windows
        # etire la fenetre et tout devient flou.
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    Chrono().mainloop()


if __name__ == "__main__":
    main()
