package com.vdt.dataplatform.controller;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.core.io.Resource;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;

/**
 * Serves CSV exports produced by the Python worker. The worker stores the CSV in
 * Redis under a random token (15-minute TTL) and hands the chat a download URL
 * pointing here. This endpoint is public (see SecurityConfig): the token is the
 * capability, and the data was already row-level-security filtered at export time.
 */
@RestController
@RequestMapping("/api/exports")
public class ExportController {

    private static final String KEY_PREFIX = "csv_export:";

    @Autowired
    private StringRedisTemplate redisTemplate;

    @GetMapping("/{token}")
    public ResponseEntity<Resource> download(@PathVariable String token) {
        // Only accept a plain hex/UUID token — never let arbitrary input build a Redis key.
        if (token == null || !token.matches("[a-fA-F0-9\\-]{16,64}")) {
            return ResponseEntity.badRequest().build();
        }

        String csv = redisTemplate.opsForValue().get(KEY_PREFIX + token);
        if (csv == null) {
            // Expired (past TTL) or never existed.
            return ResponseEntity.status(HttpStatus.GONE).build();
        }

        String filename = redisTemplate.opsForValue().get(KEY_PREFIX + token + ":filename");
        if (filename == null || filename.isBlank()) {
            filename = "export.csv";
        }

        // Prepend a UTF-8 BOM so Excel correctly renders non-ASCII values (e.g. Vietnamese).
        byte[] bytes;
        try {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            out.write(0xEF);
            out.write(0xBB);
            out.write(0xBF);
            out.write(csv.getBytes(StandardCharsets.UTF_8));
            bytes = out.toByteArray();
        } catch (Exception e) {
            bytes = csv.getBytes(StandardCharsets.UTF_8);
        }

        ByteArrayResource resource = new ByteArrayResource(bytes);
        return ResponseEntity.ok()
                .header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"" + filename + "\"")
                .contentType(MediaType.parseMediaType("text/csv; charset=UTF-8"))
                .contentLength(bytes.length)
                .body(resource);
    }
}
