import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess, re, threading, os, time

### Fonctions utilitaires FFmpeg

def get_video_duration(input_file):
    """Retourne la durée totale de la vidéo en secondes."""
    cmd = [
        'ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'format=duration', 
        '-of', 'default=noprint_wrappers=1:nokey=1',
        input_file
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        return float(result.stdout.strip())
    except Exception:
        return 0

def run_ffmpeg_with_progress(cmd, total_duration, log_callback, progress_callback):
    """
    Exécute une commande FFmpeg et utilise log_callback(message) et
    progress_callback(percentage) pour mettre à jour la progression.
    Retourne le contenu complet de stderr.
    """
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    last_progress = 0
    stderr_lines = []
    while True:
        line = process.stderr.readline()
        if line == '' and process.poll() is not None:
            break
        if line:
            stderr_lines.append(line)
            time_match = re.search(r"time=(\d+:\d+:\d+\.\d+)", line)
            if time_match:
                h, m, s = time_match.group(1).split(':')
                current_time = int(h)*3600 + int(m)*60 + float(s)
                progress = (current_time / total_duration) * 100
                if progress - last_progress >= 1:
                    log_callback(f"Progression FFmpeg : {progress:.1f}% (Traitement: {int(current_time)}s/{int(total_duration)}s)")
                    progress_callback(progress)
                    last_progress = progress
    process.wait()
    return "".join(stderr_lines)

def detect_silences(input_file, video_duration, noise_threshold='-35dB', min_silence_duration=0.8, log_callback=None, progress_callback=None):
    """
    Utilise FFmpeg pour détecter les silences et retourne une liste de tuples (start, end).
    Si log_callback et progress_callback sont fournis, la progression est affichée.
    """
    cmd = [
        'ffmpeg', '-i', input_file,
        '-af', f"silencedetect=noise={noise_threshold}:d={min_silence_duration}",
        '-f', 'null', '-'
    ]
    if log_callback and progress_callback:
        log_callback("Détection des silences en cours...")
        stderr_output = run_ffmpeg_with_progress(cmd, video_duration, log_callback, progress_callback)
    else:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stderr_output = result.stderr

    silence_starts = re.findall(r'silence_start: (\d+\.?\d*)', stderr_output)
    silence_ends   = re.findall(r'silence_end: (\d+\.?\d*)', stderr_output)
    silences = list(zip([float(s) for s in silence_starts],
                        [float(e) for e in silence_ends]))
    if log_callback:
        log_callback(f"{len(silences)} silences détectés.")
    return silences

def get_active_segments(silences, video_duration, min_active_duration=1.0):
    """Retourne les segments actifs (entre les silences)."""
    segments = []
    prev_end = 0.0
    for s_start, s_end in silences:
        if s_start - prev_end > min_active_duration:
            segments.append((prev_end, s_start))
        prev_end = s_end
    if video_duration - prev_end > min_active_duration:
        segments.append((prev_end, video_duration))
    return segments

def score_segment(input_file, start, duration):
    """
    Calcule un score pour un segment via volumedetect (plus le score est élevé, meilleur est le segment).
    """
    cmd = [
        'ffmpeg', '-hide_banner', '-ss', str(start), '-t', str(duration),
        '-i', input_file, '-af', 'volumedetect', '-f', 'null', '-'
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stderr = result.stderr
    m = re.search(r"max_volume: (-?\d+\.?\d*) dB", stderr)
    n = re.search(r"mean_volume: (-?\d+\.?\d*) dB", stderr)
    if m and n:
        max_vol = float(m.group(1))
        mean_vol = float(n.group(1))
        if max_vol <= -40:
            return 0
        vol_factor = (max_vol + 40) / 40
        dyn_factor = abs(mean_vol - max_vol) / abs(mean_vol) if mean_vol != 0 else 1
        return duration * vol_factor * dyn_factor
    return 0

def extract_segment(input_file, start, duration, output_file, pad=0.3):
    """
    Extrait et réencode un segment sans aucun effet supplémentaire.
    Forcer 60 fps, synchronisation constante et +faststart pour un démarrage rapide.
    """
    new_start = max(0, start - pad)
    new_duration = duration + (pad if new_start == 0 else 2 * pad)
    cmd = [
        'ffmpeg', '-y',
        '-ss', str(new_start),
        '-t', str(new_duration),
        '-i', input_file,
        '-r', '60',
        '-vsync', 'cfr',
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
        '-movflags', '+faststart',
        '-c:a', 'aac', '-b:a', '192k',
        output_file
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def concatenate_segments(processed_files, output_file):
    """
    Concatène les segments extraits à l'aide du demuxer concat de FFmpeg.
    """
    list_file = "segments.txt"
    with open(list_file, "w") as f:
        for seg in processed_files:
            f.write(f"file '{os.path.abspath(seg)}'\n")
    cmd = [
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
        '-i', list_file, '-c', 'copy', output_file
    ]
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

### Interface Graphique avec Tkinter

class CutGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("AutoEditor Video - Cut Only")
        
        # Variables
        self.input_file = tk.StringVar()
        self.output_file = tk.StringVar(value="highlights.mp4")
        
        # Interface
        tk.Label(root, text="Fichier Stream:").grid(row=0, column=0, sticky="e", padx=5, pady=5)
        tk.Entry(root, textvariable=self.input_file, width=50).grid(row=0, column=1, padx=5, pady=5)
        tk.Button(root, text="Parcourir...", command=self.browse_input).grid(row=0, column=2, padx=5, pady=5)
        
        tk.Label(root, text="Fichier de sortie:").grid(row=1, column=0, sticky="e", padx=5, pady=5)
        tk.Entry(root, textvariable=self.output_file, width=50).grid(row=1, column=1, padx=5, pady=5)
        tk.Button(root, text="Enregistrer...", command=self.browse_output).grid(row=1, column=2, padx=5, pady=5)
        
        self.progress = ttk.Progressbar(root, orient="horizontal", length=400, mode="determinate")
        self.progress.grid(row=2, column=0, columnspan=3, padx=5, pady=5)
        
        self.log_text = tk.Text(root, height=15, width=70, state="disabled")
        self.log_text.grid(row=3, column=0, columnspan=3, padx=5, pady=5)
        
        self.start_button = tk.Button(root, text="Démarrer", command=self.start_process)
        self.start_button.grid(row=4, column=1, pady=5)
    
    def browse_input(self):
        filename = filedialog.askopenfilename(title="Sélectionnez le fichier vidéo", 
                                              filetypes=[("Video Files", "*.mp4 *.mkv *.mov")])
        if filename:
            self.input_file.set(filename)
    
    def browse_output(self):
        filename = filedialog.asksaveasfilename(title="Enregistrer le fichier de sortie", 
                                                defaultextension=".mp4", 
                                                filetypes=[("MP4", "*.mp4")])
        if filename:
            self.output_file.set(filename)
    
    def log(self, message):
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")
    
    def update_progress(self, value):
        self.progress['value'] = value
        self.root.update_idletasks()
    
    def start_process(self):
        if not self.input_file.get() or not self.output_file.get():
            messagebox.showerror("Erreur", "Veuillez sélectionner un fichier d'entrée et un fichier de sortie.")
            return
        self.start_button.config(state="disabled")
        threading.Thread(target=self.run_cut_process, daemon=True).start()
    
    def run_cut_process(self):
        self.log("Démarrage du processus...")
        input_file = self.input_file.get()
        output_file = self.output_file.get()
        video_duration = get_video_duration(input_file)
        self.log(f"Durée totale du stream : {video_duration:.2f} s")
        
        # Durée cible (interpolation entre 14 et 22 minutes)
        if video_duration <= 7200:
            target_duration = 14 * 60
        elif video_duration >= 18000:
            target_duration = 22 * 60
        else:
            ratio = (video_duration - 7200) / (18000 - 7200)
            target_duration = (14 * 60) + ratio * ((22 - 14) * 60)
        self.log(f"Durée cible du highlight : {target_duration/60:.2f} minutes")
        
        # Détection des silences avec progression
        silences = detect_silences(input_file, video_duration, noise_threshold='-35dB', min_silence_duration=0.8, log_callback=self.log, progress_callback=self.update_progress)
        active_segments = get_active_segments(silences, video_duration, min_active_duration=1.0)
        self.log(f"{len(active_segments)} segments actifs identifiés.")
        
        scored_segments = []
        self.log("Analyse et scoring des segments...")
        for seg in active_segments:
            s_start, s_end = seg
            seg_dur = s_end - s_start
            score = score_segment(input_file, s_start, seg_dur)
            scored_segments.append((s_start, s_end, seg_dur, score))
        scored_segments = [s for s in scored_segments if s[3] > 0]
        scored_segments.sort(key=lambda x: x[3], reverse=True)
        self.log(f"{len(scored_segments)} segments avec score positif.")
        
        selected_segments = []
        total = 0
        for seg in scored_segments:
            if total < target_duration:
                s_start, s_end, seg_dur, _ = seg
                remaining = target_duration - total
                if seg_dur > remaining:
                    seg_dur = remaining
                    s_end = s_start + seg_dur
                selected_segments.append((s_start, s_end, seg_dur))
                total += seg_dur
        self.log(f"{len(selected_segments)} segments sélectionnés (total = {total:.2f} s).")
        selected_segments.sort(key=lambda x: x[0])
        
        processed_files = []
        self.log("Extraction des segments...")
        os.makedirs("temp", exist_ok=True)
        for i, seg in enumerate(selected_segments):
            s_start, s_end, seg_dur = seg
            out_seg = os.path.join("temp", f"seg_{i}.mp4")
            self.log(f"Extraction du segment {i}: {s_start:.2f}s à {s_end:.2f}s")
            extract_segment(input_file, s_start, seg_dur, out_seg, pad=0.3)
            processed_files.append(out_seg)
        
        self.log("Concaténation des segments...")
        result = concatenate_segments(processed_files, output_file)
        if result.returncode != 0:
            self.log("Erreur lors de la concaténation :")
            self.log(result.stderr)
        else:
            self.log("Processus terminé avec succès !")
            self.update_progress(100)
        self.start_button.config(state="normal")

if __name__ == "__main__":
    root = tk.Tk()
    app = CutGUI(root)
    root.mainloop()
