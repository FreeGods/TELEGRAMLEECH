FROM mysterysd/wzmlx:v3

WORKDIR /usr/src/app

RUN chmod 777 /usr/src/app

# ✅ Install FFmpeg and required dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ✅ Create symlink for mediaforge (BinConfig.FFMPEG_NAME)
# Isso garante que tanto "ffmpeg" quanto "mediaforge" funcionem
RUN ln -sf /usr/bin/ffmpeg /usr/bin/mediaforge

# ✅ Verificar se ffmpeg está instalado corretamente
RUN ffmpeg -version && mediaforge -version

RUN uv venv --system-site-packages

COPY requirements.txt .
RUN uv pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["bash", "start.sh"]
