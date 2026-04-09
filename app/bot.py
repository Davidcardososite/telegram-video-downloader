import os
import uuid
import yt_dlp
import asyncio
import logging
import hashlib
from typing import Dict
from datetime import datetime
from telegram.error import NetworkError, TimedOut
import time
from telegram.constants import ParseMode
import traceback
import sys

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler, 
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# Configuração do logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class DownloadVideo:
    def __init__(self, telegram_token: str):
        self.telegram_token = telegram_token
        
        # Cache simples em memória
        self.cache = {}

        self.UPLOAD_FOLDER = "uploads"
        self.MAX_FILE_SIZE = 2000 * 1024 * 1024  # 2GB limite do Telegram
        self.CLEANUP_INTERVAL = 86400  # 24 horas
        self.ADMIN_IDS = []  # IDs de administradores (opcional)

        # Dicionários para armazenar estados
        self.active_downloads: Dict[int, Dict] = {}
        self.user_sessions: Dict[int, Dict] = {}
        
        # Cria a pasta de uploads se não existir
        os.makedirs(self.UPLOAD_FOLDER, exist_ok=True)

    # Função para criar hash da URL
    def create_url_hash(self, url: str) -> str:
        return hashlib.md5(url.encode()).hexdigest()[:16]

    # Comando /start
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        welcome_text = f"""👋 Olá, {user.first_name}!

📥 *Bot de Download de Vídeos*

*Comandos disponíveis:*
/start - Mostrar esta mensagem
/help - Ajuda e instruções
/download - Baixar vídeo (ou envie URL diretamente)
/cancel - Cancelar download em andamento
/status - Ver status do download
/formats - Ver formatos disponíveis
/clean - Limpar downloads (admin)

*Formatos suportados:* YouTube, Instagram, Facebook, TikTok, Twitter/X

⚠️ *Termos de uso:* Use apenas para conteúdo que você tem permissão para baixar.
"""
        
        keyboard = [
            [InlineKeyboardButton("📥 Baixar Vídeo", callback_data="download")],
            [InlineKeyboardButton("ℹ️ Ajuda", callback_data="help")],
            [InlineKeyboardButton("📝 Termos", callback_data="terms")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')

    # Comando /help
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = """📖 *Como usar o bot:*

1. *Envie uma URL* de vídeo ou use /download
2. *Escolha a qualidade* desejada
3. *Aguarde o processamento*
4. *Receba o vídeo* automaticamente

*Comandos:*
/download - Iniciar download
/cancel - Cancelar operação atual
/status - Ver progresso
/formats - Ver formatos disponíveis

*Limitações:*
• Máximo 2GB por arquivo
• Formatos: MP4, WebM, MKV
• Suporte a playlists (somente primeiro vídeo)

*Problemas comuns:* Se o download falhar, tente:
• Outra qualidade
• Verificar se o vídeo é público
• Enviar URL novamente
"""
        await update.message.reply_text(help_text, parse_mode='Markdown')

    # Manipulador de callback
    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        if query.data == "download":
            await query.edit_message_text(
                "📤 *Envie a URL do vídeo que deseja baixar:*\n\n"
                "Exemplos:\n"
                "• YouTube: https://youtu.be/...\n"
                "• Instagram: https://www.instagram.com/reel/...\n"
                "• TikTok: https://www.tiktok.com/@.../video/...",
                parse_mode='HTML'
            )
        elif query.data == "help":
            await query.edit_message_text(
                "📖 *Como usar o bot:*\n\n"
                "1. <b>Envie uma URL</b> de vídeo\n"
                "2. <b>Escolha a qualidade</b> desejada\n"
                "3. <b>Aguarde o processamento</b>\n"
                "4. <b>Receba o vídeo</b> automaticamente\n\n"
                "<i>Comandos: /download, /cancel, /status</i>",
                parse_mode='HTML'
            )
        elif query.data == "terms":
            await query.edit_message_text(
                "📝 *Termos de Uso:*\n\n"
                "1. <b>Uso Responsável:</b> Apenas para conteúdo com permissão\n"
                "2. <b>Direitos Autorais:</b> Respeite os direitos autorais\n"
                "3. <b>Limitações:</b> Nem todos os vídeos funcionam\n"
                "4. <b>Privacidade:</b> Arquivos apagados em 24h\n"
                "5. <b>Uso Justo:</b> Evite downloads excessivos\n"
                "6. <b>Isenção:</b> Desenvolvedor não se responsabiliza\n\n"
                "<i>Última atualização: 05/01/2026</i>",
                parse_mode='HTML'
            )

    # Comando /download
    async def download_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        # Verificar se já tem download ativo
        if user_id in self.active_downloads:
            await update.message.reply_text(
                "⚠️ Você já tem um download em andamento. "
                "Use /status para ver o progresso ou /cancel para cancelar."
            )
            return
        
        await update.message.reply_text(
            "📤 *Envie a URL do vídeo:*\n\n"
            "Suporto: YouTube, Instagram, Facebook, TikTok, Twitter/X",
            parse_mode='Markdown'
        )

    # Comando /formats
    async def formats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        formats_text = """🎬 *Formatos disponíveis:*

*YouTube:*
• best - Melhor qualidade (vídeo+áudio)
• bestvideo - Melhor vídeo apenas
• worst - Pior qualidade
• 720p, 480p, 360p - Qualidades específicas
• mp4 - Formato MP4

*Geral (para outras plataformas):*
• Padrão: Melhor qualidade disponível

*Para escolher:* Envie a URL e selecione a qualidade no menu.
"""
        await update.message.reply_text(formats_text, parse_mode='Markdown')

    # Comando /status
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        if user_id in self.active_downloads:
            status = self.active_downloads[user_id]
            status_text = f"""📊 *Status do Download:*

🔤 *Status:* {status.get('status', 'Processando')}
📥 *Progresso:* {status.get('progress', '0%')}
⚡ *Velocidade:* {status.get('speed', '0 MB/s')}
⏱️ *Tempo restante:* {status.get('time_remaining', 'Calculando...')}
"""
            await update.message.reply_text(status_text, parse_mode='HTML')
        else:
            await update.message.reply_text("📭 Nenhum download ativo no momento.")

    # Comando /cancel
    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        if user_id in self.active_downloads:
            del self.active_downloads[user_id]
            if user_id in self.user_sessions:
                del self.user_sessions[user_id]
            await update.message.reply_text("✅ Download cancelado com sucesso.")
        else:
            await update.message.reply_text("ℹ️ Não há downloads ativos para cancelar.")

    # Comando /clean (admin)
    async def clean_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        # Verificar se é admin (se ADMIN_IDS estiver configurado)
        if self.ADMIN_IDS and user_id not in self.ADMIN_IDS:
            await update.message.reply_text("⛔ Comando restrito a administradores.")
            return
        
        try:
            count = self.limpar_uploads()
            await update.message.reply_text(f"🧹 {count} arquivos temporários removidos.")
        except Exception as e:
            await update.message.reply_text(f"❌ Erro ao limpar: {str(e)}")

    # Processar URL recebida
    async def handle_url(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        url = update.message.text.strip()
        user_id = update.effective_user.id
        
        # Validar URL
        if not url.startswith(('http://', 'https://')):
            await update.message.reply_text(
                "❌ URL inválida. Envie uma URL completa começando com http:// ou https://"
            )
            return
        
        # Verificar se já tem download ativo
        if user_id in self.active_downloads:
            await update.message.reply_text(
                "⚠️ Você já tem um download em andamento. "
                "Use /status para ver o progresso ou /cancel para cancelar."
            )
            return
        
        # Armazenar URL na sessão do usuário
        url_hash = self.create_url_hash(url)
        self.user_sessions[user_id] = {
            'url': url,
            'url_hash': url_hash,
            'timestamp': datetime.now()
        }
        
        # Mostrar opções de qualidade
        keyboard = [
            [
                InlineKeyboardButton("🎬 Melhor", callback_data=f"q_best_{url_hash}"),
                InlineKeyboardButton("📱 720p", callback_data=f"q_720_{url_hash}")
            ],
            [
                InlineKeyboardButton("⚡ MP4", callback_data=f"q_mp4_{url_hash}"),
                InlineKeyboardButton("📉 Menor", callback_data=f"q_worst_{url_hash}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"🔍 *URL recebida:* `{url[:50]}...`\n\n"
            "📊 *Selecione a qualidade desejada:*",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    # Processar seleção de qualidade
    async def handle_quality_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        data = query.data
        
        if not data.startswith('q_'):
            await query.edit_message_text("❌ Erro ao processar seleção.")
            return
        
        # Extrair qualidade e hash da URL
        parts = data.split('_')
        if len(parts) < 3:
            await query.edit_message_text("❌ Dados inválidos.")
            return
        
        quality_type = parts[1]  # best, 720, mp4, worst
        url_hash = parts[2]
        
        # Mapear tipos para formatos do yt-dlp
        quality_map = {
            'best': 'bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4] / bv*+ba/b',
            '720': 'bestvideo[height<=720]+bestaudio/best[height<=720]',
            'mp4': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'worst': 'worst'
        }
        
        quality = quality_map.get(quality_type, 'best')
        
        # Verificar se a sessão ainda existe
        if user_id not in self.user_sessions or self.user_sessions[user_id]['url_hash'] != url_hash:
            await query.edit_message_text("❌ Sessão expirada. Envie a URL novamente.")
            return
        
        url = self.user_sessions[user_id]['url']
        
        # Registrar download ativo
        self.active_downloads[user_id] = {
            'status': 'Iniciando...',
            'progress': '0%',
            'start_time': datetime.now(),
            'url': url,
            'quality': quality_type
        }
        
        await query.edit_message_text(
            f"⏬ *Iniciando download...*\n\n"
            f"🎬 Qualidade: {quality_type}\n"
            f"⏳ Isso pode levar alguns minutos...",
            parse_mode='Markdown'
        )
        
        # Iniciar download em background
        asyncio.create_task(self.download_video(update, context, url, quality, user_id))

    # Logger customizado para yt-dlp
    class MyLogger:
        def debug(self, msg):
            # Ignorar mensagens de debug
            pass
            
        def info(self, msg):
            logger.info(f"yt-dlp: {msg}")
            
        def warning(self, msg):
            logger.warning(f"yt-dlp: {msg}")
            
        def error(self, msg):
            logger.error(f"yt-dlp: {msg}")

    # Função para limpar uploads antigos
    def limpar_uploads(self):
        """Remove arquivos com mais de 24 horas da pasta de uploads."""
        try:
            count = 0
            current_time = time.time()
            
            for filename in os.listdir(self.UPLOAD_FOLDER):
                filepath = os.path.join(self.UPLOAD_FOLDER, filename)
                
                # Verificar se é arquivo e se tem mais de 24 horas
                if os.path.isfile(filepath):
                    file_age = current_time - os.path.getmtime(filepath)
                    if file_age > self.CLEANUP_INTERVAL:
                        try:
                            os.remove(filepath)
                            count += 1
                        except Exception as e:
                            logger.error(f"Erro ao remover {filepath}: {e}")
            
            return count
        except Exception as e:
            logger.error(f"Erro em limpar_uploads: {e}")
            return 0

    # Função principal de download
    async def download_video(self, update: Update, context: ContextTypes.DEFAULT_TYPE, url: str, quality: str, user_id: int):
        chat_id = update.effective_chat.id
        unique_id = uuid.uuid4()
        video_path = None
        
        try:
            # Atualizar status
            self.active_downloads[user_id]['status'] = 'Analisando URL...'
            
            await context.bot.send_chat_action(
                chat_id=chat_id,
                action='typing'
            )
            
            # Configurar opções do yt-dlp
            ydl_opts = {
                'format': quality,
                'outtmpl': os.path.join(self.UPLOAD_FOLDER, f'%(title)s_{unique_id}.%(ext)s'),
                'cookiefile': 'all_cookies.txt' if os.path.exists('all_cookies.txt') else None,
                'noplaylist': True,
                'ignoreerrors': True,
                'logger': self.MyLogger(),
                'progress_hooks': [lambda d: self.progress_hook(d, user_id)],
                'postprocessors': [{
                    'key': 'FFmpegVideoConvertor',
                    'preferedformat': 'mp4',
                }],
                'quiet': True,
                'no_warnings': True,
            }
            
            self.active_downloads[user_id]['status'] = 'Baixando...'
            
            # Baixar vídeo
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Primeiro obter informações
                info_dict = ydl.extract_info(url, download=False)
                video_title = info_dict.get('title', 'Vídeo')
                
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"📥 *Baixando:* {video_title[:100]}...",
                    parse_mode='HTML'
                )
                
                # Agora baixar
                ydl.download([url])
                
                # Encontrar arquivo baixado
                base_filename = ydl.prepare_filename(info_dict)
                video_path = None
                
                for ext in ['.mp4', '.webm', '.mkv', '.part']:
                    test_path = os.path.splitext(base_filename)[0] + ext
                    if os.path.exists(test_path):
                        if ext != '.part':  # Ignorar arquivos incompletos
                            video_path = test_path
                        break
            
            if not video_path or not os.path.exists(video_path):
                raise Exception("Arquivo não encontrado após download")
            
            # Verificar tamanho do arquivo
            file_size = os.path.getsize(video_path)
            if file_size > self.MAX_FILE_SIZE:
                os.remove(video_path)
                raise Exception(f"Arquivo muito grande ({file_size/(1024*1024):.1f}MB). Limite: {self.MAX_FILE_SIZE/(1024*1024)}MB")
            
            # Enviar vídeo para o usuário
            self.active_downloads[user_id]['status'] = 'Enviando...'
            
            await context.bot.send_chat_action(
                chat_id=chat_id,
                action='upload_video'
            )
            
            # Obter informações do vídeo
            video_title = os.path.basename(video_path).split('_')[0]
            file_size_mb = file_size / (1024 * 1024)
            
            with open(video_path, 'rb') as video_file:
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=video_file,
                    caption=f"✅ *Download concluído!*\n\n"
                           f"📁 *Título:* {video_title[:50]}\n"
                           f"📊 *Tamanho:* {file_size_mb:.1f} MB\n"
                           f"🎬 *Formato:* MP4\n"
                           f"🕒 *Hora:* {datetime.now().strftime('%H:%M:%S')}",
                    parse_mode='Markdown',
                    supports_streaming=True,
                    read_timeout=120,
                    write_timeout=120,
                    connect_timeout=120,
                    pool_timeout=120
                )
            
            # Mensagem de sucesso
            await context.bot.send_message(
                chat_id=chat_id,
                text="✅ *Processo finalizado com sucesso!*\n\n"
                     "Use /download para baixar outro vídeo.",
                parse_mode='Markdown'
            )
            
        except yt_dlp.utils.DownloadError as e:
            if "Private video" in str(e):
                error_msg = "❌ *Vídeo privado!*\nEste vídeo é privado ou requer login."
            elif "Video unavailable" in str(e):
                error_msg = "❌ *Vídeo indisponível!*\nEste vídeo foi removido ou é restrito."
            elif "Sign in" in str(e):
                error_msg = "❌ *Acesso restrito!*\nEste vídeo requer verificação de idade ou login."
            else:
                error_msg = f"❌ *Erro no download:*\n`{str(e)[:150]}`"
            
            await context.bot.send_message(
                chat_id=chat_id,
                text=error_msg,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            error_msg = f"❌ *Erro no download:*\n\n`{str(e)[:200]}`"
            await context.bot.send_message(
                chat_id=chat_id,
                text=error_msg,
                parse_mode='Markdown'
            )
            logger.error(f"Erro no download para usuário {user_id}: {str(e)}")
        
        finally:
            # Limpar estados
            if user_id in self.active_downloads:
                elapsed = (datetime.now() - self.active_downloads[user_id]['start_time']).seconds
                logger.info(f"Download finalizado para {user_id} em {elapsed}s")
                del self.active_downloads[user_id]
            
            if user_id in self.user_sessions:
                del self.user_sessions[user_id]
            
            # Limpar arquivo temporário
            try:
                if video_path and os.path.exists(video_path):
                    os.remove(video_path)
            except Exception as e:
                logger.error(f"Erro ao remover arquivo: {e}")

    # Hook de progresso
    def progress_hook(self, d, user_id):
        if user_id in self.active_downloads:
            if d['status'] == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate')
                downloaded = d.get('downloaded_bytes', 0)
                
                if total and total > 0:
                    progress = (downloaded / total) * 100
                    speed = d.get('_speed_str', 'N/A')
                    
                    # Atualizar apenas a cada 10% ou a cada 5 segundos
                    current_time = datetime.now()
                    last_update = self.active_downloads[user_id].get('last_update')
                    
                    if not last_update or (current_time - last_update).seconds >= 5 or progress - self.active_downloads[user_id].get('last_progress', 0) >= 10:
                        self.active_downloads[user_id].update({
                            'status': 'Baixando',
                            'progress': f'{progress:.1f}%',
                            'speed': speed,
                            'last_update': current_time,
                            'last_progress': progress
                        })
            
            elif d['status'] == 'finished':
                self.active_downloads[user_id]['status'] = 'Processando...'
                self.active_downloads[user_id]['progress'] = '100%'

    # Tarefa de limpeza automática
    async def auto_cleanup(self, context: ContextTypes.DEFAULT_TYPE):
        try:
            count = self.limpar_uploads()
            if count > 0:
                logger.info(f"Limpeza automática: {count} arquivos removidos")
                
                # Limpar sessões expiradas (mais de 1 hora)
                current_time = datetime.now()
                expired_users = []
                for user_id, session in self.user_sessions.items():
                    if (current_time - session['timestamp']).seconds > 3600:
                        expired_users.append(user_id)
                
                for user_id in expired_users:
                    if user_id in self.user_sessions:
                        del self.user_sessions[user_id]
        
        except Exception as e:
            logger.error(f"Erro na limpeza automática: {e}")

    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler global de erros."""
        try:
            error = str(context.error)
            
            # Log do erro
            logger.error(f"Exception while handling an update: {context.error}")
            
            # Erros de rede
            if isinstance(context.error, (NetworkError, TimedOut)):
                print(f"🌐 Erro de rede detectado: {error}")
                
                # Se houver um update, tenta responder
                if update and update.effective_message:
                    try:
                        await update.effective_message.reply_text(
                            "⚠️ *Problema de conexão detectado.*\n"
                            "Tente novamente em alguns segundos.",
                            parse_mode=ParseMode.MARKDOWN
                        )
                    except:
                        pass
            
            # Outros erros
            else:
                print(f"❌ Erro não tratado: {error}")
                traceback.print_exc()
                
        except Exception as e:
            print(f"❌ Erro no handler de erros: {e}")
            traceback.print_exc()

    def run(self):
        """Inicia o bot."""
        
        # Criar Application
        # Configura timeouts muito maiores para conexão inicial
        application = Application.builder() \
            .token(self.telegram_token) \
            .read_timeout(60.0) \
            .write_timeout(60.0) \
            .connect_timeout(60.0) \
            .pool_timeout(60.0) \
            .build()
        
        # Adicionar handlers
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("download", self.download_command))
        application.add_handler(CommandHandler("formats", self.formats_command))
        application.add_handler(CommandHandler("status", self.status_command))
        application.add_handler(CommandHandler("cancel", self.cancel_command))
        application.add_handler(CommandHandler("clean", self.clean_command))
        
        # Handler para botões inline
        application.add_handler(CallbackQueryHandler(self.button_handler, pattern="^(download|help|terms)$"))
        application.add_handler(CallbackQueryHandler(self.handle_quality_selection, pattern="^q_"))
        
        # Handler para URLs
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_url))
        
        # Configurar limpeza automática
        job_queue = application.job_queue
        if job_queue:
            job_queue.run_repeating(self.auto_cleanup, interval=self.CLEANUP_INTERVAL, first=10)
        
        # Handler de erro global
        application.add_error_handler(self.error_handler)
        
        # Iniciar o bot
        print("🤖 Bot de Download de Vídeos iniciado! Pressione Ctrl+C para parar.")
        
        # Loop principal com tratamento de erros
        try:
            # Loop principal
            application.run_polling(
                poll_interval=5.0,
                timeout=60,
                drop_pending_updates=True,
                allowed_updates=Update.ALL_TYPES,
                close_loop=False  # Importante: não fechar o loop
            )
        except KeyboardInterrupt:
            print("\n🛑 Bot interrompido pelo usuário.")
            self.running = False
            sys.exit(0)
        except Exception as e:
            logger.error(f"Erro fatal no bot: {e}")
            traceback.print_exc()
            self.running = False
            
            # Em vez de reiniciar automaticamente, apenas informar o erro
            print(f"\n❌ Bot caiu com erro: {e}")
            print("📝 Para reiniciar, execute o script novamente.")
            sys.exit(1)

# Função principal
def main():
    """Função principal."""
    # Obter tokens das variáveis de ambiente
    TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    
    if not TELEGRAM_TOKEN:
        print("❌ ERRO: TELEGRAM_BOT_TOKEN não encontrado!")
        print("Por favor, defina a variável de ambiente:")
        print("export TELEGRAM_BOT_TOKEN='seu_token_aqui'")
        print("Ou crie um arquivo .env com: TELEGRAM_BOT_TOKEN=seu_token")
        return
    
    # Criar bot
    bot = DownloadVideo(
        telegram_token=TELEGRAM_TOKEN
    )
    
    bot.run()

if __name__ == '__main__':
    main()