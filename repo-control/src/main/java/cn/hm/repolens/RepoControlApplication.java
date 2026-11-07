package cn.hm.repolens;
import java.time.Clock;
import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.*;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;
import org.springframework.scheduling.annotation.EnableScheduling;
@SpringBootApplication @MapperScan("cn.hm.repolens.persistence") @EnableScheduling
public class RepoControlApplication {
 public static void main(String[]args){SpringApplication.run(RepoControlApplication.class,args);}
 @Bean Clock clock(){return Clock.systemUTC();}
}
