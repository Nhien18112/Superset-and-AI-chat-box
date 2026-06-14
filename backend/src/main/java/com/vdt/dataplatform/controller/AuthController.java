package com.vdt.dataplatform.controller;

import com.vdt.dataplatform.dto.JwtResponse;
import com.vdt.dataplatform.dto.LoginRequest;
import com.vdt.dataplatform.model.User;
import com.vdt.dataplatform.repository.UserRepository;
import com.vdt.dataplatform.security.JwtUtils;
import jakarta.validation.Valid;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.Optional;

@RestController
@RequestMapping("/api/auth")
public class AuthController {

    @Autowired
    private JwtUtils jwtUtils;

    @Autowired
    private UserRepository userRepository;

    @PostMapping("/login")
    public ResponseEntity<?> authenticateUser(@Valid @RequestBody LoginRequest loginRequest) {
        Optional<User> userOpt = userRepository.findByUsername(loginRequest.getUsername());
        
        if (userOpt.isPresent()) {
            User user = userOpt.get();
            // The DB has {noop} prefix for passwords, we'll strip it for simple comparison
            String dbPassword = user.getPassword().replace("{noop}", "");
            
            if (dbPassword.equals(loginRequest.getPassword())) {
                String jwt = jwtUtils.generateJwtToken(user.getUsername());
                return ResponseEntity.ok(new JwtResponse(jwt, user.getUsername()));
            }
        }
        
        return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body("Error: Unauthorized");
    }
}
