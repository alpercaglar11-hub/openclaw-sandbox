# Build stage for React app
FROM node:20-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

# Production stage with nginx
FROM nginx:alpine

# Fix nginx cache dirs for non-root
RUN mkdir -p /var/cache/nginx/client_temp /var/cache/nginx/proxy_temp /var/log/nginx \
    && chown -R nginx:nginx /var/cache/nginx /var/log/nginx 2>/dev/null || true

# Copy nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy built assets
COPY --from=builder /app/dist /var/www/html

EXPOSE 80

HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
  CMD wget -qO- http://localhost/health || exit 1

CMD ["nginx", "-g", "daemon off;"]
