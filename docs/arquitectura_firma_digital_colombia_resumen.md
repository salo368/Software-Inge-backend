# Arquitectura de firma digital en Colombia — Resumen

## 1. Idea principal

Separar claramente tres actores:

- **Entidad de certificación/autenticadora:** aporta la infraestructura de confianza, certificados y, según el esquema, el servicio que utiliza la clave privada.
- **Nuestra plataforma:** presta el servicio de firma, gestiona el flujo, documentos, autenticación, evidencia y verificación.
- **Firmante:** es la persona cuya identidad y voluntad quedan vinculadas a la firma.

La idea no es que la plataforma simplemente diga `"Juan firmó este PDF"`, sino que exista evidencia criptográficamente verificable de que una determinada identidad firmó una representación concreta del documento y que este no fue alterado.

## 2. Arquitectura conceptual

```text
                 ENTIDAD DE CERTIFICACIÓN
              ┌─────────────────────────┐
              │ Certificado             │
              │ Clave privada           │
              │ HSM / infraestructura   │
              │ de confianza            │
              └────────────┬────────────┘
                           │
                    servicio de firma
                           │
                           ▼
              ┌─────────────────────────┐
              │ NUESTRA PLATAFORMA      │
              │ - flujo de firma        │
              │ - autenticación         │
              │ - documentos            │
              │ - evidencia             │
              │ - verificación          │
              └────────────┬────────────┘
                           │
                           ▼
                        USUARIO
```

## 3. Papel de la entidad de certificación

La entidad de certificación constituye la raíz de confianza y puede proporcionar certificados, infraestructura de claves, validación de certificados y servicios de firma.

La clave privada asociada a un certificado no debería estar simplemente guardada en nuestro backend si la identidad/certificado pertenece a otra entidad o persona.

```text
Entidad de certificación
        │
        ├── certificado
        └── clave privada
               │
             HSM /
       infraestructura segura
               │
               ▼
          Firma(hash)
```

Nuestra plataforma puede solicitar una operación de firma al servicio correspondiente sin necesariamente poseer la clave privada.

## 4. Papel de nuestra plataforma

Nuestra plataforma sería principalmente un **servicio de firma, gestión de evidencia y verificación**:

```text
1. Recibir documento
2. Crear transacción de firma
3. Identificar/autenticar firmante
4. Presentar documento
5. Obtener consentimiento
6. Solicitar OTP/biometría según el flujo
7. Obtener la firma criptográfica
8. Generar/conservar documento firmado
9. Conservar evidencia
10. Exponer servicio de verificación
```

## 5. Flujo externo

```text
1. Subir/recibir documento
        ↓
2. Identificarse
        ↓
3. Cédula / biometría
        ↓
4. Recibir OTP
        ↓
5. Ver documento
        ↓
6. Aceptar
        ↓
7. Firmar
        ↓
8. Recibir documento firmado
```

## 6. Flujo interno

```text
Documento
    ↓
SHA-256 + versión
    ↓
Almacenamiento protegido
    ↓
SigningTransaction
    ↓
Identificación/autenticación
    ↓
Eventos de auditoría
    ↓
Consentimiento
    ↓
Hash del documento aceptado
    ↓
Servicio de firma
    ↓
Firma criptográfica
    ↓
PDF firmado
    ↓
Hash del resultado
    ↓
Evidence Package
    ↓
Almacenamiento/conservación
```

## 7. Ejemplo de firma

```text
contrato.pdf
     ↓
SHA-256
     ↓
ABC123
     ↓
firma criptográfica
     ↓
Signature
```

Posteriormente:

```text
PDF recibido
     ↓
SHA-256
     ↓
ABC123
     ↓
Verify(PublicKey, ABC123, Signature)
     ↓
VALID
```

Si el PDF cambia:

```text
PDF original    → ABC123
PDF modificado  → XYZ789
```

la verificación deja de coincidir.

## 8. Certificado y clave privada

```text
Certificado
    ↓
identidad + clave pública
```

La clave privada se utiliza para generar la firma:

```text
Signature
    +
Public Key
    +
Document Hash
    ↓
Verification
```

Si la entidad externa mantiene la clave:

```text
Nuestra plataforma
       │
       │ "firma este hash"
       ▼
Entidad de certificación
       │
       │ clave privada protegida
       ▼
Firma criptográfica
       │
       ▼
Nuestra plataforma
```

## 9. Dos firmas conceptualmente diferentes

### Firma del usuario

Relaciona al firmante con el documento:

```text
Usuario
  ↓
Identificación
  ↓
Autenticación
  ↓
Consentimiento
  ↓
Firma
  ↓
Documento
```

### Firma de evidencia de la plataforma

Puede proteger la integridad/procedencia de un paquete de evidencia:

```text
Evidence Package
      ↓
SHA-256
      ↓
Firma de la plataforma / infraestructura correspondiente
      ↓
Evidence verificable
```

La segunda no sustituye a la primera. La firma de la plataforma no demuestra por sí sola que el usuario quiso firmar.

## 10. Evidence Package

La plataforma debería poder reconstruir posteriormente la transacción:

```text
evidence/
├── original.pdf
├── signed.pdf
├── manifest.json
├── authentication-events.json
├── consent-events.json
├── signature.json
├── audit-log.json
└── hashes.json
```

Ejemplo:

```json
{
  "transaction_id": "TX-123",
  "document_hash": "ABC123",
  "signed_document_hash": "XYZ789",
  "signer": "USR-456",
  "signed_at": "2026-09-20T21:30:00Z",
  "identity_verified": true,
  "otp_verified": true,
  "consent": true
}
```

Debe permitir responder:

- ¿Quién firmó?
- ¿Qué documento firmó?
- ¿Qué versión?
- ¿Cuándo?
- ¿Cómo fue autenticado?
- ¿Qué consentimiento dio?
- ¿Qué firma se generó?
- ¿El documento fue modificado?

## 11. Servicio de verificación

```http
POST /documents/verify
```

Proceso:

```text
PDF
 ↓
SHA-256
 ↓
Comparar con el valor firmado
 ↓
Validar firma criptográfica
 ↓
Validar certificado/cadena de confianza
 ↓
Validar vigencia/revocación según corresponda
 ↓
Resultado
```

Respuesta conceptual:

```json
{
  "valid": true,
  "document_integrity": true,
  "signature_valid": true,
  "certificate_valid": true,
  "signed_at": "2026-09-20T21:30:00Z",
  "transaction_id": "TX-123"
}
```

## 12. Verificación posterior

La cadena esencial es:

```text
Documento
   ↓
Hash
   ↓
Firma
   ↓
Certificado
   ↓
Clave pública
   ↓
Verificación
```

La evidencia adicional permite reconstruir el contexto de la firma.

## 13. Modelo jurídico/técnico colombiano

La **Ley 527 de 1999** regula los mensajes de datos y la firma digital. Para una firma digital contempla, entre otros aspectos, que la firma:

- sea única para la persona que la usa;
- sea susceptible de verificación;
- esté bajo el control exclusivo de quien la usa;
- esté ligada al mensaje de forma que una modificación invalide la firma.

El régimen colombiano también contempla las entidades de certificación y los certificados asociados.

Por eso, para representar conceptualmente una firma digital regulada:

```text
Entidad de certificación
        ↓
Certificado / infraestructura de confianza
        ↓
Servicio de firma
        ↓
Nuestra plataforma
        ↓
Documento + evidencia
        ↓
Servicio de verificación
```

Debe distinguirse cuidadosamente entre **firma electrónica** y **firma digital**, y entre una entidad que proporciona autenticación y una entidad de certificación que opera bajo el régimen correspondiente.

## 14. Arquitectura completa

```text
                    ┌───────────────────────┐
                    │ ENTIDAD DE            │
                    │ CERTIFICACIÓN         │
                    │                       │
                    │ Certificado           │
                    │ Clave privada         │
                    │ HSM / confianza       │
                    └───────────┬───────────┘
                                │
                         servicio de firma
                                │
                                ▼
┌────────────┐       ┌───────────────────────┐
│  USUARIO   │──────▶│ NUESTRA PLATAFORMA    │
└────────────┘       │                       │
                     │ Identity/Auth         │
                     │ Signing               │
                     │ Documents             │
                     │ Evidence              │
                     │ Verification          │
                     └───────────┬───────────┘
                                 │
                    ┌────────────┼─────────────┐
                    ▼            ▼             ▼
                Original     Signed PDF     Evidence
                + hash       + signature    package
                    │            │             │
                    └────────────┼─────────────┘
                                 ▼
                         almacenamiento
                          protegido / WORM
                                 │
                                 ▼
                         /verify/document
                                 │
                                 ▼
                         Verificación
                         criptográfica
```

## 15. Explicación en una frase

> **La entidad de certificación aporta la confianza criptográfica y el certificado; nuestra plataforma orquesta el proceso de firma, autenticación, gestión documental y evidencia; y el servicio de verificación permite comprobar posteriormente la integridad del documento y la validez de la firma.**

La plataforma no se limita a almacenar `"Juan firmó"`, sino que conserva y permite verificar:

```text
"Este documento concreto tiene esta huella,
esta firma corresponde al certificado indicado,
la firma puede verificarse criptográficamente
y existe evidencia de cómo se realizó la operación."
```

## 16. Para el proyecto universitario

Se puede modelar una **Mock CA** que emita certificados de prueba y un **Signing Service** que utilice claves protegidas:

```text
Mock CA
  ↓
Certificado del firmante
  ↓
Signing Service
  ↓
PDF + firma digital + certificado
  ↓
Evidence Store
  ↓
Verification Service
```

Esto permite demostrar el flujo criptográfico completo sin pretender que el proyecto sea, por sí mismo, una entidad de certificación real.
