import logging
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from threading import Thread
from logging.handlers import RotatingFileHandler
import whisper
import warnings
import os
from docx import Document
import webbrowser
from plyer import notification
import winsound
import json
from platform import system
import subprocess

# Classe personalizada para evitar a abertura de janelas de console no Windows
class NoConsolePopen(subprocess.Popen):
    """
    A custom Popen class that disables creation of a console window in Windows.
    """
    def __init__(self, args, **kwargs):
        if system() == 'Windows' and 'startupinfo' not in kwargs:
            kwargs['startupinfo'] = subprocess.STARTUPINFO()
            kwargs['startupinfo'].dwFlags |= subprocess.STARTF_USESHOWWINDOW
        super().__init__(args, **kwargs)

# Substituindo subprocess.Popen pela classe personalizada
subprocess.Popen = NoConsolePopen

warnings.filterwarnings("ignore", category=FutureWarning, message="FP16 is not supported on CPU; using FP32 instead")
warnings.filterwarnings("ignore", category=UserWarning, message="FP16 is not supported on CPU; using FP32 instead")

CONFIG_FILE = "config.json"
DEFAULT_CONFIG = {
    "model_path": "",
    "language": "pt"
}

if not os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(DEFAULT_CONFIG, f, indent=4)
    logging.info(f"Arquivo de configuração criado: {CONFIG_FILE}")

config = {}
try:
    with open(CONFIG_FILE, 'r') as f:
        config = json.load(f)
except FileNotFoundError:
    pass

def configurar_logger():
    if not os.path.exists("logs"):
        os.makedirs("logs")
    
    log_handler = RotatingFileHandler('logs/info.log', maxBytes=5*1024*1024, backupCount=5)
    log_handler.setLevel(logging.INFO)
    log_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.addHandler(log_handler)

configurar_logger()

cancelar_desgravacao = False

def extrair_audio(filepath, temp_dir):
    try:
        # Verifica se o arquivo já é um formato de áudio suportado
        if filepath.lower().endswith(('.mp3', '.wav', '.aac', '.flac', '.m4a', '.ogg')):
            logging.info(f"O arquivo {filepath} já é um formato de áudio suportado. Não é necessário extrair o áudio.")
            return filepath
        
        logging.info(f"Extraindo áudio do vídeo: {filepath}")
        
        
        output_path = os.path.join(temp_dir, "temp_audio.aac") # ./temp/temp_audio.acc
        output_path = os.path.abspath(output_path)  
        
        command = ['ffmpeg', '-i', filepath, '-acodec', 'aac', output_path, '-y']
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logging.info(f"FFmpeg output: {result}")

        if result.returncode != 0:
            logging.error(f"Erro ao extrair áudio com ffmpeg: {result.stderr.decode()}")
            raise subprocess.CalledProcessError(result.returncode, command, output=result.stdout, stderr=result.stderr)
        
        logging.info(f"Áudio extraído com sucesso para: {output_path}")
        return output_path
    except subprocess.CalledProcessError as e:
        logging.error(f"Erro ao extrair áudio com ffmpeg: {e.stderr.decode()}")
        raise

def extrair_e_transcrever(filepaths, text_var, btn_abrir, btn_select, btn_modelo, model_path):
    global cancelar_desgravacao

    result = None  

    try:
        logging.info(f"Tentando carregar o modelo do caminho: {model_path}")
        model = whisper.load_model(model_path)
        if model:
            logging.info(f"Modelo de transcrição carregado com sucesso")
    except Exception as e:
        logging.error(f"Erro ao carregar o modelo de transcrição: {e}")
        text_var.set(f"Erro ao carregar o modelo. Verifique o caminho.")
        return

    temp_dir = "./temp"
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)
        logging.info(f"Diretório temporário criado: {temp_dir}")

    for filepath in filepaths:
        filepath = filepath.replace("/", "\\") 
        logging.info(f"Analisando arquivo: {filepath}")
        text_var.set("Processando arquivos...")

        if cancelar_desgravacao:
            text_var.set("Desgravação cancelada. Selecione arquivos para começar.")
            btn_select.config(text="Selecionar Arquivos",
                              command=lambda: iniciar_processo(btn_abrir, btn_select, btn_modelo))
            btn_modelo.config(state=tk.NORMAL)
            cancelar_desgravacao = False
            logging.info("Desgravação cancelada pelo usuário.")
            return

        nome_arquivo = os.path.splitext(os.path.basename(filepath))[0]
        local_salvamento = os.path.join(os.path.dirname(filepath), nome_arquivo + "_text.docx")
        local_salvamento = local_salvamento.replace("/", "\\") 
        logging.info(f"Transcrição será salva em: {local_salvamento}")

        try:
            if not os.path.exists(filepath):
                raise FileNotFoundError(f"O arquivo {filepath} não foi encontrado.")

            audio_path = extrair_audio(filepath, temp_dir)

            # Verifique se o arquivo de áudio foi realmente criado
            if not os.path.exists(audio_path):
                raise FileNotFoundError(f"O arquivo de áudio extraído não foi encontrado: {audio_path}")

            text_var.set(f"Desgravando: {nome_arquivo} ⏳ Por favor, aguarde.")
            logging.info(f"Iniciando transcrição do arquivo: {audio_path}")

            result = model.transcribe(audio_path, language="pt")

            doc = Document()
            for segment in result["segments"]:
                text = segment["text"]
                doc.add_paragraph(text)

            doc.save(local_salvamento)
            logging.info(f"Transcrição concluída salva em: {local_salvamento}")

            if audio_path != filepath:
                os.remove(audio_path)

        except FileNotFoundError as fnf_error:
            logging.error(f"Erro ao transcrever (fnf_error) {nome_arquivo}. Motivo: {fnf_error}")
            cancelar_desgravacao = True
            text_var.set(f"Erro no desgravando {nome_arquivo}.")
            btn_select.config(text="Selecionar Arquivos para transcrição",
                              command=lambda: iniciar_processo(btn_abrir, btn_select, btn_modelo))
            btn_modelo.config(state=tk.NORMAL)
            notification.notify(
                title="Erro na Transcrição",
                message=f"O arquivo {filepath} não foi encontrado.",
                timeout=10
            )
            winsound.MessageBeep(winsound.MB_ICONHAND)
            return

        except PermissionError as perm_error:
            logging.error(f"Erro ao transcrever (PermissionError) {nome_arquivo}. Motivo: {perm_error}")
            cancelar_desgravacao = True
            text_var.set(f"Erro no desgravando {nome_arquivo}.")
            btn_select.config(text="Selecionar Arquivos para transcrição",
                              command=lambda: iniciar_processo(btn_abrir, btn_select, btn_modelo))
            btn_modelo.config(state=tk.NORMAL)
            notification.notify(
                title="Erro na Transcrição",
                message=f"Permissão negada para acessar o arquivo {filepath}.",
                timeout=10
            )
            winsound.MessageBeep(winsound.MB_ICONHAND)
            return

        except ValueError as val_error:
            logging.error(f"Erro ao transcrever (val_error) {nome_arquivo}. Motivo: {val_error}")
            cancelar_desgravacao = True
            text_var.set(f"Erro no desgravando {nome_arquivo}.")
            btn_select.config(text="Selecionar Arquivos para transcrição",
                              command=lambda: iniciar_processo(btn_abrir, btn_select, btn_modelo))
            btn_modelo.config(state=tk.NORMAL)
            notification.notify(
                title="Erro na Transcrição",
                message=f"O arquivo {filepath} não contém uma faixa de áudio.",
                timeout=10
            )
            winsound.MessageBeep(winsound.MB_ICONHAND)
            return

        except Exception as e:
            logging.error(f"Erro ao transcrever (Generic) {nome_arquivo}. Motivo: {e}")
            cancelar_desgravacao = True
            text_var.set(f"Erro no desgravando {nome_arquivo}.")
            btn_select.config(text="Selecionar Arquivos para transcrição",
                              command=lambda: iniciar_processo(btn_abrir, btn_select, btn_modelo))
            btn_modelo.config(state=tk.NORMAL)
            notification.notify(
                title="Erro na Transcrição",
                message=f"Ocorreu um erro ao transcrever {nome_arquivo}.",
                timeout=10
            )
            winsound.MessageBeep(winsound.MB_ICONHAND)
            return

    text_var.set("Todas as transcrições foram concluídas.")
    btn_select.config(text="Selecionar Arquivos",
                      command=lambda: iniciar_processo(btn_abrir, btn_select, btn_modelo))
    btn_modelo.config(state=tk.NORMAL)
    btn_abrir.config(state=tk.NORMAL, command=lambda: abrir_local_salvamento(filepaths))

    logging.info("Todas as transcrições foram concluídas com sucesso.")
    notification.notify(
        title="Transcrição Concluída",
        message="Todas as transcrições foram concluídas com sucesso.",
        timeout=10
    )
    winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)

def abrir_local_salvamento(filepaths):
    if filepaths:
        diretorio = os.path.dirname(filepaths[0])
        webbrowser.open(diretorio)
        logging.info(f"Abrindo diretório de salvamento: {diretorio}")

def iniciar_transcricao_thread(filepaths, text_var, btn_abrir, btn_select, btn_modelo, model_path):
    Thread(target=lambda: extrair_e_transcrever(filepaths, text_var, btn_abrir, btn_select, btn_modelo, model_path)).start()

def selecionar_arquivo_e_salvar(text_var, btn_select, btn_abrir, btn_modelo, model_path):
    global cancelar_desgravacao
    filepaths = filedialog.askopenfilenames(title="Escolher os vídeos que serão transcritos para texto",
                                            filetypes=[("Arquivos Selecionáveis", "*.mp4;*.mp3;*.wav;*.mkv"),("MP4 files", "*.mp4",), ("MP3 files", "*.mp3"),("WAV files", "*.wav")])
    if not filepaths:
        text_var.set("Seleção de arquivo cancelada. Operação interrompida.")
        logging.info("Seleção de arquivo cancelada pelo usuário.")
        return None

    filepaths = [filepath.replace("/", "\\") for filepath in filepaths] 

    text_var.set(f"{len(filepaths)} arquivo(s) selecionado(s) para transcrição.")
    btn_select.config(text="Cancelar desgravação", command=lambda: cancelar_desgravacao_fn(btn_select, btn_modelo))
    btn_modelo.config(state=tk.DISABLED)
    btn_abrir.config(state=tk.DISABLED)
    logging.info(f"{len(filepaths)} arquivo(s) selecionado(s) para transcrição.")
    return filepaths

def cancelar_desgravacao_fn(btn_select, btn_modelo):
    global cancelar_desgravacao
    cancelar_desgravacao = True
    btn_select.config(text="Selecionar Arquivos", command=lambda: iniciar_processo(btn_abrir, btn_select, btn_modelo))
    btn_modelo.config(state=tk.NORMAL)
    text_var.set("Cancelamento em processo...")
    logging.info("Processo de desgravação cancelado pelo usuário.")

def selecionar_modelo():
    janela_modelo = tk.Toplevel()
    janela_modelo.title("Selecionar Modelo Whisper")
    janela_modelo.geometry("400x200")
    janela_modelo.grab_set()

    label = ttk.Label(janela_modelo, text="Selecione o caminho do modelo:")
    label.pack(pady=10)

    model_path_var_local = tk.StringVar(value=config.get('model_path', ''))

    entry = ttk.Entry(janela_modelo, textvariable=model_path_var_local, width=50)
    entry.pack(pady=10)

    def escolher_modelo():
        filepath = filedialog.askopenfilename(title="Selecionar Modelo Whisper", filetypes=[("Modelo Whisper", "*.pt")])
        if filepath:
            model_path_var_local.set(filepath)
            try:
                whisper.load_model(filepath)
                config['model_path'] = filepath
                with open(CONFIG_FILE, 'w') as f:
                    json.dump(config, f)
                model_path_var.set(filepath)
                messagebox.showinfo("Sucesso", "Modelo carregado e caminho salvo com sucesso!")
                janela_modelo.destroy()
            except Exception as e:
                messagebox.showerror("Erro", f"Erro ao carregar o modelo: {e}")
                logging.info(f"Modelo inicial carregado com sucesso. {e}")

    btn_escolher = ttk.Button(janela_modelo, text="Escolher Modelo", command=escolher_modelo)
    btn_escolher.pack(pady=10)

def verificar_modelo_inicial():
    model_path = config.get('model_path')
    if model_path:
        try:
            whisper.load_model(model_path)
            logging.info("Modelo inicial carregado com sucesso.")
        except Exception as e:
            logging.error(f"Erro ao carregar o modelo inicial: {e}")
            messagebox.showerror("Erro", f"Erro ao carregar o modelo inicial: {e}")
            selecionar_modelo()
    else:
        selecionar_modelo()

root = tk.Tk()
root.title("TextifyVoice [ Beta ] by@felipe.sh")

root.geometry("650x500")

root.iconbitmap('./bin/icon.ico')

cor_fundo = "#343a40"
root.configure(bg=cor_fundo)

style = ttk.Style()
style.theme_use('clam')

cor_frente = "#f8f9fa"
cor_acento = "#007bff"
cor_modelo = "#28a745"

style.configure("TFrame", background=cor_fundo)
style.configure("TButton", background=cor_acento, foreground=cor_frente, font=("Arial", 10, "bold"), borderwidth=1, relief="flat")
style.configure("Modelo.TButton", background=cor_modelo, foreground=cor_frente, font=("Arial", 10, "bold"), borderwidth=1, relief="flat")
style.configure("TLabel", background=cor_fundo, foreground=cor_frente, font=("Arial", 12))
style.configure("Title.TLabel", background=cor_fundo, foreground=cor_frente, font=("Arial", 16, "bold"))

style.map("TButton", relief=[("pressed", "sunken"), ("active", "raised")])
style.map("Modelo.TButton", relief=[("pressed", "sunken"), ("active", "raised")])

title_frame = ttk.Frame(root, style="TFrame", height=70)
title_frame.pack(side=tk.TOP, fill=tk.X)
title_frame.pack_propagate(False)

titulo = ttk.Label(title_frame, text="Transcritor de Vídeo", style="Title.TLabel", anchor="center")
titulo.pack(side=tk.TOP, fill=tk.X, pady=20)

frame = ttk.Frame(root, style="TFrame")
frame.pack(expand=True, fill=tk.BOTH, padx=20, pady=20)

text_var = tk.StringVar()
text_var.set("Selecione os arquivos MP4 para transcrever.")
text_label = ttk.Label(frame, textvariable=text_var, wraplength=550, style="TLabel")
text_label.pack()

model_path = config.get('model_path')
model_path_var = tk.StringVar(value=model_path)

btn_abrir = ttk.Button(frame, text="Abrir Pasta de Documentos Transcritos", state=tk.DISABLED, style="TButton")
btn_select = ttk.Button(frame, text="Selecionar Arquivos", style="TButton")
btn_modelo = ttk.Button(frame, text="Selecionar Modelo", command=selecionar_modelo, style="Modelo.TButton")

def iniciar_processo(btn_abrir, btn_select, btn_modelo):
    filepaths = selecionar_arquivo_e_salvar(text_var, btn_select, btn_abrir, btn_modelo, model_path_var.get())
    if filepaths:
        iniciar_transcricao_thread(filepaths, text_var, btn_abrir, btn_select, btn_modelo, model_path_var.get())

btn_select.config(command=lambda: iniciar_processo(btn_abrir, btn_select, btn_modelo))
btn_select.pack(pady=(10, 0))
btn_abrir.pack(pady=(10, 20))
btn_modelo.pack(pady=(10, 0))

root.after(100, verificar_modelo_inicial)

root.mainloop()