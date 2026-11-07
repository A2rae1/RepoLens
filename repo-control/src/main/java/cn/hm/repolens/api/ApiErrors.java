package cn.hm.repolens.api;

import cn.hm.repolens.domain.DomainException;
import java.util.Map;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.*;

@RestControllerAdvice
public class ApiErrors {
    @ExceptionHandler(DomainException.class)
    public ResponseEntity<?> domain(DomainException e) { return ResponseEntity.status(e.status()).body(Map.of("code",e.code(),"message",e.getMessage())); }
    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<?> invalid(MethodArgumentNotValidException e) { return ResponseEntity.badRequest().body(Map.of("code","INVALID_INPUT","message","字段不合法，请检查输入")); }
    @ExceptionHandler(DataIntegrityViolationException.class)
    public ResponseEntity<?> duplicate(DataIntegrityViolationException e) { return ResponseEntity.status(409).body(Map.of("code","CONSTRAINT_CONFLICT","message","请求与现有记录冲突，请使用原幂等键查询结果")); }
}
