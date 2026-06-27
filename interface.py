import pygame
import socket
import time
import sys
import cv2
import threading
import numpy as np
import urllib.request 

UDP_IP = "192.168.4.1"
UDP_PORT = 4210
URL_CAMERA = "http://192.168.4.1/"

NEUTRE = 90
DIR_GAUCHE = 45   
DIR_DROITE = 135  
MOT_MORT = 90

class CameraThread(threading.Thread):
    def __init__(self, url):
        threading.Thread.__init__(self)
        self.url = url
        self.frame = None
        self.running = True
        self.connected = False

    def run(self):
        bytes_data = b''
        while self.running:
            try:
                stream = urllib.request.urlopen(self.url, timeout=5)
                self.connected = True
                while self.running:
                    chunk = stream.read(16384)
                    if not chunk: break
                    bytes_data += chunk
                    a = bytes_data.find(b'\xff\xd8')
                    b = bytes_data.find(b'\xff\xd9')
                    if a != -1 and b != -1:
                        if a < b:
                            jpg = bytes_data[a:b+2]
                            bytes_data = bytes_data[b+2:]
                            if len(bytes_data) > 200000: bytes_data = b''
                            try:
                                frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
                                if frame is not None:
                                    frame = cv2.flip(frame, -1) 
                                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                                    self.frame = np.transpose(frame_rgb, (1, 0, 2))
                            except: pass 
                        else:
                            bytes_data = bytes_data[a:]
            except:
                self.connected = False
                time.sleep(1)

    def stop(self):
        self.running = False

def wait_for_step(ecran, font_titre, font_texte, titre, instructions, w, h):
    waiting = True
    while waiting:
        pygame.event.pump()
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE): sys.exit()
            if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE: waiting = False
        ecran.fill((30, 30, 45))
        ecran.blit(font_titre.render(titre, True, (0, 255, 100)), (w//2 - 200, h//2 - 150))
        for i, txt in enumerate(instructions):
            color = (255, 200, 0) if "ESPACE" in txt else (255, 255, 255)
            ecran.blit(font_texte.render(txt, True, color), (w//2 - 200, h//2 - 80 + i * 40))
        pygame.display.flip()
        time.sleep(0.05)

def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)

    pygame.init()
    pygame.joystick.init()
    if pygame.joystick.get_count() == 0: sys.exit()
    volant = pygame.joystick.Joystick(0)
    volant.init()
    nb_axes = volant.get_numaxes()
    nb_boutons = volant.get_numbuttons()

    ecran = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    SCREEN_W, SCREEN_H = ecran.get_size()
    font_titre = pygame.font.Font(None, 40)
    font_texte = pygame.font.Font(None, 30)
    
    wait_for_step(ecran, font_titre, font_texte, "Étalonnage (1/3) : Point mort", 
                  ["Veuillez relâcher entièrement le volant et les pédales.", "", "Appuyez sur la touche ESPACE pour continuer."], SCREEN_W, SCREEN_H)
    axes_repos = [volant.get_axis(i) for i in range(nb_axes)]

    wait_for_step(ecran, font_titre, font_texte, "Étalonnage (2/3) : Accélérateur", 
                  ["Veuillez maintenir la pédale d'accélérateur enfoncée au maximum.", "", "Appuyez sur la touche ESPACE pour continuer."], SCREEN_W, SCREEN_H)
    axes_gaz = [volant.get_axis(i) for i in range(nb_axes)]
    AXE_GAZ = max(range(nb_axes), key=lambda i: abs(axes_gaz[i] - axes_repos[i]))
    
    wait_for_step(ecran, font_titre, font_texte, "Étalonnage (3/3) : Frein", 
                  ["Veuillez maintenir la pédale de frein enfoncée au maximum.", "", "Appuyez sur la touche ESPACE pour continuer."], SCREEN_W, SCREEN_H)
    axes_frein = [volant.get_axis(i) for i in range(nb_axes)]
    AXE_FREIN = max(range(nb_axes), key=lambda i: abs(axes_frein[i] - axes_repos[i]))

    cam_thread = CameraThread(URL_CAMERA)
    cam_thread.start()
    en_cours = True
    horloge = pygame.time.Clock()

    def norm_pedal(val, repos, enfonce):
        if abs(enfonce - repos) < 0.05: return 0.0
        return max(0.0, min(1.0, (val - repos) / (enfonce - repos)))

    dernier_envoi_udp = 0 # Timer pour la limitation de la fréquence d'envoi UDP

    while en_cours:
        pygame.event.pump()
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                en_cours = False

        direction = int(90 + (volant.get_axis(0) * 45))
        direction = max(DIR_GAUCHE, min(DIR_DROITE, direction))

        norm_gaz = norm_pedal(volant.get_axis(AXE_GAZ), axes_repos[AXE_GAZ], axes_gaz[AXE_GAZ])
        norm_frein = norm_pedal(volant.get_axis(AXE_FREIN), axes_repos[AXE_FREIN], axes_frein[AXE_FREIN])
        
        if norm_frein > 0.05: moteur = int(90 - (norm_frein * 30))
        elif norm_gaz > 0.05: moteur = int(90 + (norm_gaz * 30))
        else: moteur = MOT_MORT

        klaxon_actif = 1 if any(volant.get_button(i) for i in range(nb_boutons)) else 0

        # Limitation du taux d'envoi UDP (20 Hz max)
        maintenant = time.time()
        if maintenant - dernier_envoi_udp > 0.05:
            try: 
                sock.sendto(f"{direction},{moteur},{klaxon_actif}".encode('utf-8'), (UDP_IP, UDP_PORT))
                dernier_envoi_udp = maintenant
            except: pass

        ecran.fill((0, 0, 0)) 
        if cam_thread.frame is not None:
            surf = pygame.transform.scale(pygame.surfarray.make_surface(cam_thread.frame), (SCREEN_W, SCREEN_H))
            ecran.blit(surf, (0, 0))
            
        ecran.blit(font_texte.render(f"Direction : {direction}°", True, (0, 255, 0)), (20, 20))
        ecran.blit(font_texte.render(f"Propulsion : {moteur} (Accélérateur : {norm_gaz*100:.0f}%, Frein : {norm_frein*100:.0f}%)", True, (0, 255, 0)), (20, 60))
        
        couleur_klaxon = (255, 0, 0) if klaxon_actif else (0, 255, 0)
        ecran.blit(font_texte.render(f"Avertisseur sonore : {'Actif' if klaxon_actif else 'Inactif'}", True, couleur_klaxon), (20, 100))
        
        pygame.display.flip()
        horloge.tick(60)

    volant.quit()
    cam_thread.stop()
    cam_thread.join() 
    try: sock.sendto(f"{NEUTRE},{NEUTRE},0".encode('utf-8'), (UDP_IP, UDP_PORT))
    except: pass
    pygame.quit()

if __name__ == '__main__':
    main()