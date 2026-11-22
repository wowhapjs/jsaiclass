FROM node:22-alpine
WORKDIR /app
COPY aiclass1/api/package.json ./
RUN npm install --omit=dev --no-audit --no-fund
COPY aiclass1/api/server.mjs ./
USER 1030:1030
EXPOSE 3000
CMD ["node","server.mjs"]
