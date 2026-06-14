package com.vdt.dataplatform.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

@Data
public class LoginRequest {
    @NotBlank
    private String username;
    
    // We mock password for this implementation since it's just a mock stock platform
    private String password;
}
