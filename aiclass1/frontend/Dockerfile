FROM nginx:alpine
COPY aiclass1/frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html /usr/share/nginx/html/index.html
COPY aiclass1/frontend/dist/ /usr/share/nginx/html/aiclass1/
EXPOSE 80
