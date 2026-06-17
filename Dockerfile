# Stage 1: Build frontend
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./

# Guard against Git-LFS pointer files leaking into the build context.
# If someone runs `docker build` without first running `git lfs pull`,
# the assets are 131-byte text pointers, not real binaries — silent in
# `npm run build` but a broken logo at runtime. Fail fast here instead.
RUN if head -c 50 public/assets/vastra-mark-v2.png | grep -q "git-lfs"; then \
      echo "ERROR: public/assets/vastra-mark-v2.png is a Git-LFS pointer." >&2; \
      echo "Run 'git lfs install && git lfs pull' on the host before docker build." >&2; \
      exit 1; \
    fi

RUN npm run build

# Stage 2: Backend runtime
FROM python:3.11-slim
WORKDIR /app

# Install backend dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend/ ./backend/

# Copy frontend build to static directory
COPY --from=frontend-build /app/frontend/dist ./static

# Run as non-root user
RUN useradd --create-home --uid 1000 app && chown -R app:app /app
USER app

EXPOSE 8000

CMD ["uvicorn", "backend.hf_main:app", "--host", "0.0.0.0", "--port", "8000"]
