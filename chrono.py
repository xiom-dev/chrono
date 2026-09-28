#!/usr/bin/python3
"""Chrono — chronomètre et compte à rebours, aux couleurs de ZyRoom.

Python + GTK4, comme ZyRoom-GTK : tout ce qu'il faut est déjà sur le système
(GTK 4, GStreamer pour le son, Python). L'appli, c'est ce seul fichier.

Deux modes, choisis en haut de la fenêtre :

* **Compte à rebours** : on règle heures, minutes et secondes — au clavier,
  ou à la molette de la souris posée sur le champ —, puis « Lancer ». Au bout,
  le son choisi dans les options est joué **une seule fois**.
* **Chronomètre** : « Lancer » part de zéro, « Arrêter » fige le temps.

« Arrêter » coupe le décompte **et** le son s'il joue.

La dernière durée lancée est mémorisée dans ~/.config/chrono/reglages.json :
à la réouverture, elle est déjà dans les champs, « Lancer » suffit.

Lancer : ~/chrono/chrono.py
"""
import json
import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gst", "1.0")
from gi.repository import Gdk, Gio, GLib, Gst, Gtk  # noqa: E402

# Les couleurs de ZyRoom : fond ardoise, texte gris clair, jaune "or" pour le
# temps, vert sarcelle pour l'action, rouge pour l'arret.
CSS = """
/* Tout le style vise le contenu (.contenu), jamais la barre de titre : un
   "button { padding }" general epaississait aussi fermer / reduire /
   agrandir, et la barre avec eux. */
window, dialog { background: #10171a; color: #e2e8e6; font-size: 15px; }
headerbar.fine { min-height: 32px; padding: 0 4px; background: #172226;
                 color: #e2e8e6; box-shadow: none; border-bottom: 1px solid #1e2c31; }
headerbar.fine .title { font-size: 13px; font-weight: 700; }
headerbar.fine windowcontrols button { min-height: 20px; min-width: 20px;
                                       padding: 2px; margin: 0 2px; }
.contenu button { background: #1e2c31; color: #e2e8e6; border: 1px solid #172226;
         border-radius: 8px; padding: 8px 16px; box-shadow: none; }
.contenu button:hover { border-color: #7fb3a2; }
.contenu button:checked { background: #3f7a68; color: #ffffff; }
.contenu button.lancer { background: #3f7a68; color: #ffffff; font-weight: 700; }
.contenu button.arreter { color: #e2696a; font-weight: 700; }
.contenu button.pause { color: #e8c15a; font-weight: 700; }
.contenu button.symbole { font-size: 20px; padding: 4px 16px; }
.contenu button:disabled { color: #5d6b69; }
.contenu spinbutton { background: #172226; color: #e8c15a; border: 1px solid #1e2c31;
             border-radius: 8px; font-size: 28px; }
.contenu spinbutton button { padding: 4px 8px; border: none; background: none; }
.temps { color: #e8c15a; font-size: 64px; font-weight: 700; }
.contenu list { background: #172226; border-radius: 8px; }
.contenu row { padding: 2px 8px; color: #e2e8e6; }
.contenu row:selected { background: #3f7a68; color: #ffffff; }
.contenu button.ecouter { padding: 2px 10px; color: #e8c15a; }
.contenu checkbutton { color: #e2e8e6; }
.contenu checkbutton check { background: #172226; border: 1px solid #7fb3a2; }
.contenu checkbutton check:checked { background: #3f7a68; color: #ffffff; }
.faible { color: #bcc8c6; }
"""

# Le son propose d'office, s'il existe : celui du reveil de GNOME.
SON_PAR_DEFAUT = "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga"

# Le dossier ou s'ouvre le choix du son : les sonneries de GNOME.
DOSSIER_SONS = "/usr/share/sounds/freedesktop/stereo"

# Les dossiers dont les sons forment la liste des sonneries des options.
DOSSIERS_SONNERIES = (DOSSIER_SONS, "/usr/share/sounds/gnome/default/alerts")
EXTENSIONS_SON = (".oga", ".ogg", ".wav", ".mp3", ".flac", ".opus")


def sonneries(perso: list) -> list:
    """Les sons perso d'abord -- ceux choisis un jour par « Autre fichier… »,
    tant qu'ils existent --, puis ceux des dossiers de sonneries, tries par
    nom. Les voix de test des haut-parleurs (« front left »...) n'ont rien
    d'une sonnerie."""
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
    return [c for c in perso if os.path.isfile(c) and c not in trouves] + trouves


def joli_nom(chemin: str) -> str:
    """« phone-incoming-call.oga » devient « phone incoming call »."""
    return os.path.splitext(os.path.basename(chemin))[0].replace("-", " ").replace("_", " ")

# Les reglages : un petit fichier JSON, l'equivalent du localStorage du web.
REGLAGES = os.path.join(GLib.get_user_config_dir(), "chrono", "reglages.json")


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


class Chrono(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application) -> None:
        super().__init__(application=app, title="Chrono")
        # Une barre de titre a nous, pour la garder fine : celle que GTK pose
        # d'office fait 46 px, plus massive que celle des applis GNOME.
        barre = Gtk.HeaderBar()
        barre.add_css_class("fine")
        self.set_titlebar(barre)
        self.set_default_size(520, 380)
        self.reglages = lire_reglages()
        # Un son choisi hors des dossiers de sonneries entre dans la liste
        # des sons perso, et y reste.
        self.garder_perso(self.reglages.get("son", ""))

        # Le son : un "playbin" de GStreamer, qui lit tout fichier audio
        # (mp3 compris). Il joue une fois puis se tait.
        self.son = Gst.ElementFactory.make("playbin", None)
        bus = self.son.get_bus()
        bus.add_signal_watch()
        bus.connect("message::eos", lambda *_: self.couper_son())

        # Le temps : l'horloge monotone de GLib (en microsecondes), et un
        # battement qui repeint -- comme un setInterval en JavaScript.
        self.debut = 0
        self.duree_us = 0
        self.battement = 0      # l'identifiant du battement, 0 a l'arret
        # Le temps deja ecoule avant une pause, dans les deux modes : pause le
        # fige, lecture repart de la, arret l'efface et ramene au debut.
        self.cumul_us = 0
        self.en_pause = False

        pile = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        pile.add_css_class("contenu")
        for cote in ("top", "bottom", "start", "end"):
            getattr(pile, f"set_margin_{cote}")(20)
        self.set_child(pile)

        # Les deux modes : deux boutons dont un seul reste enfonce.
        modes = Gtk.Box(spacing=8)
        self.bouton_rebours = Gtk.ToggleButton(label="Compte à rebours")
        self.bouton_chrono = Gtk.ToggleButton(label="Chronomètre", group=self.bouton_rebours)
        options = Gtk.Button(label="Options")
        options.set_hexpand(True)
        options.set_halign(Gtk.Align.END)
        options.connect("clicked", lambda *_: self.ouvrir_options())
        # La saisie en secondes, a portee de main entre les modes et les
        # options : une case, visible en compte a rebours seulement.
        self.case_secondes = Gtk.CheckButton(label="En secondes",
                                             active=self.en_secondes())
        self.case_secondes.set_margin_start(8)
        self.case_secondes.connect(
            "toggled", lambda b: self.basculer_secondes(b.get_active()))
        for w in (self.bouton_rebours, self.bouton_chrono, self.case_secondes, options):
            modes.append(w)
        pile.append(modes)

        # Les trois champs du compte a rebours. Gtk.SpinButton accepte d'office
        # le clavier et la molette posee dessus, sans clic prealable.
        self.champs = Gtk.Box(spacing=8)
        self.heures = self.champ(self.champs, 99, "h")
        self.minutes = self.champ(self.champs, 59, "min")
        self.secondes = self.champ(self.champs, 59, "s")
        pile.append(self.champs)
        # La saisie en secondes seules, au choix dans les options : un seul
        # champ, pour taper 240 plutot que 0 h 4 min 0 s.
        self.champs_sec = Gtk.Box(spacing=8)
        self.en_sec = self.champ(self.champs_sec, 359999, "s")
        self.en_sec.set_wrap(False)
        self.en_sec.set_width_chars(6)
        pile.append(self.champs_sec)

        self.temps = Gtk.Label(label="00:00:00")
        self.temps.add_css_class("temps")
        self.temps.set_vexpand(True)
        pile.append(self.temps)

        self.etat = Gtk.Label(label="")
        self.etat.add_css_class("faible")
        pile.append(self.etat)

        # Les trois boutons, avec les symboles des lecteurs : lancer ou
        # reprendre, pause, arret. Le mot reste au survol.
        boutons = Gtk.Box(spacing=12, homogeneous=True)
        self.lancer = Gtk.Button(label="▶", tooltip_text="Lancer")
        self.lancer.add_css_class("lancer")
        self.lancer.connect("clicked", lambda *_: self.demarrer())
        self.pause = Gtk.Button(label="❚❚", tooltip_text="Pause")
        self.pause.add_css_class("pause")
        self.pause.connect("clicked", lambda *_: self.mettre_en_pause())
        arreter = Gtk.Button(label="■", tooltip_text="Arrêter")
        arreter.add_css_class("arreter")
        arreter.connect("clicked", lambda *_: self.stopper())
        for b in (self.lancer, self.pause, arreter):
            b.add_css_class("symbole")
            boutons.append(b)
        self.pause.set_sensitive(False)
        pile.append(boutons)

        # La derniere duree et le dernier mode, repris d'office.
        self.poser_duree(int(self.reglages.get("derniere_duree", 0)))
        if self.reglages.get("mode") == "chrono":
            self.bouton_chrono.set_active(True)
        else:
            self.bouton_rebours.set_active(True)
        self.bouton_rebours.connect("toggled", lambda *_: self.changer_de_mode())
        self.changer_de_mode()

    def champ(self, boite: Gtk.Box, maxi: int, unite: str) -> Gtk.SpinButton:
        champ = Gtk.SpinButton.new_with_range(0, maxi, 1)
        champ.set_numeric(True)
        # Passer de 59 a 0 en continuant de tourner la molette.
        champ.set_wrap(True)
        champ.set_width_chars(3)
        champ.connect("value-changed", lambda *_: self.peindre_repos())
        etiquette = Gtk.Label(label=unite)
        etiquette.add_css_class("faible")
        boite.append(champ)
        boite.append(etiquette)
        return champ

    # ------------------------------------------------------------ reglages
    def rebours(self) -> bool:
        return self.bouton_rebours.get_active()

    def chemin_son(self) -> str:
        chemin = self.reglages.get("son", "")
        if chemin and os.path.isfile(chemin):
            return chemin
        return SON_PAR_DEFAUT if os.path.isfile(SON_PAR_DEFAUT) else ""

    def garder_perso(self, chemin: str) -> None:
        perso = self.reglages.setdefault("sons_perso", [])
        if (chemin and os.path.isfile(chemin) and chemin not in perso
                and os.path.dirname(chemin) not in DOSSIERS_SONNERIES):
            perso.append(chemin)
            ecrire_reglages(self.reglages)

    def en_secondes(self) -> bool:
        return bool(self.reglages.get("en_secondes", False))

    def poser_duree(self, total: int) -> None:
        """Met une duree dans les deux saisies, h/min/s et secondes seules."""
        self.heures.set_value(total // 3600)
        self.minutes.set_value(total % 3600 // 60)
        self.secondes.set_value(total % 60)
        self.en_sec.set_value(total)

    def basculer_secondes(self, oui: bool) -> None:
        """L'option : la duree deja reglee passe d'une saisie a l'autre."""
        total = self.duree_des_champs()
        self.reglages["en_secondes"] = oui
        ecrire_reglages(self.reglages)
        self.poser_duree(total)
        self.afficher_champs()

    def afficher_champs(self) -> None:
        self.champs.set_visible(self.rebours() and not self.en_secondes())
        self.champs_sec.set_visible(self.rebours() and self.en_secondes())
        self.case_secondes.set_visible(self.rebours())

    def champs_actifs(self, oui: bool) -> None:
        self.champs.set_sensitive(oui)
        self.champs_sec.set_sensitive(oui)

    def duree_des_champs(self) -> int:
        if self.en_secondes():
            return self.en_sec.get_value_as_int()
        return (self.heures.get_value_as_int() * 3600
                + self.minutes.get_value_as_int() * 60
                + self.secondes.get_value_as_int())

    # ------------------------------------------------------------ gestes
    def changer_de_mode(self) -> None:
        self.stopper()
        self.reglages["mode"] = "rebours" if self.rebours() else "chrono"
        ecrire_reglages(self.reglages)
        self.afficher_champs()
        self.peindre_repos()

    def peindre_repos(self) -> None:
        """L'affichage a l'arret : la duree reglee, ou zero en chronometre.
        En pause, le temps fige reste affiche."""
        if self.battement or self.en_pause:
            return
        self.temps.set_label(en_texte(self.duree_des_champs()) if self.rebours()
                             else "00:00:00")

    def demarrer(self) -> None:
        """▶ : lance, ou reprend apres une pause."""
        if self.battement:
            return
        self.couper_son()
        if self.en_pause:
            # La reprise : on repart du temps fige, sans relire les champs.
            self.en_pause = False
        elif self.rebours():
            total = self.duree_des_champs()
            if total == 0:
                self.etat.set_label("Règle une durée d'abord.")
                return
            # Memorisee des le lancement : c'est elle qu'on veut retrouver.
            self.reglages["derniere_duree"] = total
            ecrire_reglages(self.reglages)
            self.duree_us = total * 1_000_000
            self.cumul_us = 0
        else:
            self.cumul_us = 0
        self.debut = GLib.get_monotonic_time() - self.cumul_us
        self.battement = GLib.timeout_add(100, self.avancer)
        self.etat.set_label("")
        self.lancer.set_sensitive(False)
        self.pause.set_sensitive(True)
        self.champs_actifs(False)
        self.avancer()

    def mettre_en_pause(self) -> None:
        """❚❚ : fige le temps ; ▶ le fera repartir de la."""
        if not self.battement:
            return
        self.cumul_us = GLib.get_monotonic_time() - self.debut
        GLib.source_remove(self.battement)
        self.battement = 0
        self.en_pause = True
        self.etat.set_label("En pause")
        self.lancer.set_sensitive(True)
        self.pause.set_sensitive(False)

    def stopper(self) -> None:
        """■ : coupe le decompte et le son, et ramene au debut -- la duree
        reglee en compte a rebours, zero en chronometre."""
        if self.battement:
            GLib.source_remove(self.battement)
            self.battement = 0
        self.en_pause = False
        self.cumul_us = 0
        self.couper_son()
        self.lancer.set_sensitive(True)
        self.pause.set_sensitive(False)
        self.champs_actifs(True)
        self.etat.set_label("")
        self.peindre_repos()

    def avancer(self) -> bool:
        """Un battement : rend True pour continuer, False pour s'arreter."""
        ecoule = GLib.get_monotonic_time() - self.debut
        if not self.rebours():
            # Le chronometre compte les secondes pleines, comme une montre.
            self.temps.set_label(en_texte(ecoule // 1_000_000))
            return True
        reste = self.duree_us - ecoule
        if reste > 0:
            # Le compte a rebours arrondit vers le haut : 0,4 s restantes
            # s'affichent encore 00:00:01, et 00:00:00 veut dire "fini".
            self.temps.set_label(en_texte((reste + 999_999) // 1_000_000))
            return True
        # Au bout : on s'arrete, on le dit, et le son part une fois.
        self.battement = 0
        self.temps.set_label("00:00:00")
        self.etat.set_label("Terminé !")
        self.cumul_us = 0
        self.lancer.set_sensitive(True)
        self.pause.set_sensitive(False)
        self.champs_actifs(True)
        self.jouer()
        return False

    # ------------------------------------------------------------ le son
    def jouer(self, chemin: str = "") -> None:
        chemin = chemin or self.chemin_son()
        if not chemin:
            self.etat.set_label(self.etat.get_label() + " (aucun son choisi)")
            return
        self.son.set_state(Gst.State.NULL)
        self.son.set_property("uri", Gst.filename_to_uri(chemin))
        self.son.set_state(Gst.State.PLAYING)

    def couper_son(self) -> None:
        self.son.set_state(Gst.State.NULL)

    # ------------------------------------------------------------ options
    def ouvrir_options(self) -> None:
        """Le choix du son joue au bout du compte a rebours."""
        fenetre = Gtk.Window(title="Options", transient_for=self, modal=True,
                             default_width=460, default_height=560)
        pile = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        pile.add_css_class("contenu")
        for cote in ("top", "bottom", "start", "end"):
            getattr(pile, f"set_margin_{cote}")(16)
        fenetre.set_child(pile)
        pile.append(Gtk.Label(label="Son joué à la fin du compte à rebours :", xalign=0))
        nom = Gtk.Label(xalign=0, wrap=True)
        nom.add_css_class("faible")
        pile.append(nom)

        # La liste des sonneries : un clic sur la ligne la choisit, le
        # bouton lecture la fait entendre sans la choisir.
        liste = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        lignes = {}
        perso = self.reglages.get("sons_perso", [])

        def ajouter_ligne(chemin, position=-1):
            boite = Gtk.Box(spacing=8)
            etiquette = Gtk.Label(label=joli_nom(chemin), xalign=0, hexpand=True)
            boite.append(etiquette)
            if chemin in perso:
                marque = Gtk.Label(label="perso")
                marque.add_css_class("faible")
                boite.append(marque)
            ecouter = Gtk.Button(label="▶", tooltip_text="Écouter")
            ecouter.add_css_class("ecouter")
            ecouter.connect("clicked", lambda _b, c=chemin: self.jouer(c))
            boite.append(ecouter)
            ligne = Gtk.ListBoxRow(child=boite)
            ligne.chemin = chemin
            lignes[chemin] = ligne
            liste.insert(ligne, position)

        for chemin in sonneries(perso):
            ajouter_ligne(chemin)

        def choisie(_liste, ligne):
            if ligne is None or ligne.chemin == self.chemin_son():
                return
            self.reglages["son"] = ligne.chemin
            ecrire_reglages(self.reglages)
            peindre()

        liste.connect("row-selected", choisie)
        defile = Gtk.ScrolledWindow(child=liste, vexpand=True,
                                    hscrollbar_policy=Gtk.PolicyType.NEVER)
        defile.set_min_content_height(260)
        pile.append(defile)

        def peindre():
            chemin = self.chemin_son()
            nom.set_label(joli_nom(chemin) if chemin else "aucun son choisi")
            # La sonnerie en cours reste surlignee dans la liste.
            if chemin in lignes:
                liste.select_row(lignes[chemin])
            else:
                liste.unselect_all()

        def choisir(*_):
            filtre = Gtk.FileFilter(name="Sons")
            filtre.add_mime_type("audio/*")
            filtres = Gio.ListStore.new(Gtk.FileFilter)
            filtres.append(filtre)
            dialogue = Gtk.FileDialog(title="Choisir un son", filters=filtres)
            # Ouvert d'office sur les sonneries de GNOME : le dossier le plus
            # fourni du PC (alarme, cloche, message, telephone...).
            if os.path.isdir(DOSSIER_SONS):
                dialogue.set_initial_folder(Gio.File.new_for_path(DOSSIER_SONS))

            def fini(d, resultat):
                try:
                    fichier = d.open_finish(resultat)
                except GLib.Error:
                    return      # annule
                chemin = fichier.get_path()
                self.reglages["son"] = chemin
                ecrire_reglages(self.reglages)
                self.garder_perso(chemin)
                # Nouveau son perso : il rejoint la liste, en tete.
                if chemin not in lignes and chemin in perso:
                    ajouter_ligne(chemin, 0)
                peindre()

            dialogue.open(fenetre, None, fini)

        rangee = Gtk.Box(spacing=8, homogeneous=True)
        for texte, action in (("Autre fichier…", choisir),
                              ("Écouter", lambda *_: self.jouer()),
                              ("Couper", lambda *_: self.couper_son())):
            b = Gtk.Button(label=texte)
            b.connect("clicked", action)
            rangee.append(b)
        pile.append(rangee)
        fermer = Gtk.Button(label="Fermer", halign=Gtk.Align.END)
        fermer.connect("clicked", lambda *_: fenetre.close())
        pile.append(fermer)
        peindre()
        fenetre.present()


def main() -> int:
    # **Un nom a soi pour le son.** PipeWire retient le volume et la sourdine
    # de chaque application par son nom ; sans celui-ci, Chrono s'appelait
    # "python3", et heritait du reglage de n'importe quel script Python --
    # muet, apres des essais en sourdine.
    GLib.set_prgname("chrono")
    GLib.set_application_name("Chrono")
    Gst.init(None)
    app = Gtk.Application(application_id="be.xiom.Chrono")

    def demarrage(app):
        style = Gtk.CssProvider()
        style.load_from_string(CSS)
        # Comme une balise <link rel="stylesheet"> : la feuille vaut pour
        # toutes les fenetres de l'appli.
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), style, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        Chrono(app).present()

    app.connect("activate", demarrage)
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
