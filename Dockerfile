FROM eclipse-temurin:21-jre
WORKDIR /app
COPY target/dsl-doris-compiler.jar /app/compiler.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/compiler.jar", "serve", "--host", "0.0.0.0", "--port", "8080"]
