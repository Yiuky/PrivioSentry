# SPDX-License-Identifier: AGPL-3.0-or-later

def is_valid_cpf(cpf_str):
    """
    Validates a CPF (Cadastro de Pessoas Físicas) using the official digit calculation algorithm.
    Accepts both formatted (000.000.000-00) and plain (00000000000) strings.
    """
    if not cpf_str:
        return False
        
    # 1. Remove non-numeric characters
    cpf = "".join(filter(str.isdigit, cpf_str))

    # 2. Check if it has 11 digits or is a sequence of repeated digits
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False

    # 3. Calculation function for digits
    def calculate_digit(base, weight):
        soma = 0
        for i, char in enumerate(base):
            soma += int(char) * (weight - i)
        
        remainder = (soma * 10) % 11
        return 0 if remainder in (10, 11) else remainder

    # 4. Calculate and compare digits
    try:
        d1 = calculate_digit(cpf[:9], 10)
        d2 = calculate_digit(cpf[:10], 11)
        return d1 == int(cpf[9]) and d2 == int(cpf[10])
    except (ValueError, IndexError):
        return False

def is_valid_cnpj(cnpj_str):
    """
    Validates a CNPJ (Cadastro Nacional da Pessoa Jurídica) using the official algorithm.
    """
    if not cnpj_str: return False
    cnpj = "".join(filter(str.isdigit, cnpj_str))
    if len(cnpj) != 14 or cnpj == cnpj[0] * 14: return False

    def calculate_cnpj_digit(base_cnpj, multipliers):
        soma = sum(int(digit) * weight for digit, weight in zip(base_cnpj, multipliers))
        remainder = soma % 11
        return 0 if remainder < 2 else 11 - remainder

    m1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    m2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    
    try:
        d1 = calculate_cnpj_digit(cnpj[:12], m1)
        d2 = calculate_cnpj_digit(cnpj[:13], m2)
        return d1 == int(cnpj[12]) and d2 == int(cnpj[13])
    except (ValueError, IndexError):
        return False
