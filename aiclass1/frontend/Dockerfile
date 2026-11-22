FROM node:22-alpine AS build
WORKDIR /site
COPY aiclass1/frontend/package*.json ./
RUN npm install --no-audit --no-fund
COPY aiclass1/frontend/ ./
RUN npm run build
FROM nginx:alpine
COPY aiclass1/frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html /usr/share/nginx/html/index.html
COPY --from=build /site/dist/ /usr/share/nginx/html/aiclass1/
EXPOSE 80
