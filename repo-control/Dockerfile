ARG JAVA_RUNTIME=eclipse-temurin:17-jre-jammy
FROM ${JAVA_RUNTIME}
WORKDIR /app
COPY target/repolens-control-0.1.0.jar /app/control.jar
USER 10001:10001
EXPOSE 8094
ENTRYPOINT ["java","-Xms64m","-Xmx256m","-jar","/app/control.jar"]
