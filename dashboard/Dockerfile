# Build stage for React app
FROM node:20-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

# Production stage with nginx
FROM nginx:alpine

# Create non-root user
RUN addgroup -r app && adduser -r -g app app

# Copy nginx config
RUN mkdir -p /etc/nginx/conf.d /var/www/html && chown -R app:app /var/www/html

# Copy built assets
COPY --from=builder /app/dist /var/www/html

# Copy nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Create logs directory
RUN mkdir -p /var/log/nginx && chown -R app:app /var/log/nginx

USER app

EXPOSE 80

HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
  CMD curl -f http://localhost/health || exit 1

CMD ["nginx", "-g", "daemon off;"]