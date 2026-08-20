variable "region" {
  description = "AWS region. eu-central-1 (Frankfurt) — найближчий до Львова, нормальні spot-ціни."
  type        = string
  default     = "eu-central-1"
}

variable "cluster_name" {
  type    = string
  default = "c3-experiment"
}

# ВАЖЛИВО: тримайте актуальну версію Kubernetes.
# Старі версії на EKS потрапляють в "extended support" і коштують $0.60/год
# замість $0.10/год — це x6 і типова пастка з несподіваним рахунком.
variable "kubernetes_version" {
  type    = string
  default = "1.33"
}

variable "node_instance_types" {
  description = "Тільки недорогі типи. Spot-ціна ~$0.03-0.04/год за ноду."
  type        = list(string)
  default     = ["m5.large", "m5a.large", "m6i.large"]
}

variable "node_count" {
  description = "3 ноди достатньо для 2000+ синтетичних ворклоадів (Pod'и без реального навантаження)."
  type        = number
  default     = 3
}

variable "node_disk_gb" {
  type    = number
  default = 30
}

variable "budget_limit_usd" {
  description = "Місячний ліміт бюджету. Алерти на 50/80/100%."
  type        = number
  default     = 25
}

variable "alert_email" {
  description = "Email для бюджетних алертів. ОБОВ'ЯЗКОВО вказати у terraform.tfvars"
  type        = string
}

# ВАЖЛИВО: без цього змінна модуля EKS дефолтиться на 0.0.0.0/0 — публічний
# API-ендпоінт доступний з усього інтернету (README про це явно каже, що НЕ так).
# Немає дефолту навмисно — вкажіть СВОЮ публічну IP у terraform.tfvars
# (напр. з https://checkip.amazonaws.com). Якщо вона зміниться (домашній
# роутер тощо), kubectl почне зависати з timeout — оновіть значення і
# зробіть terraform apply ще раз.
variable "cluster_endpoint_public_access_cidrs" {
  description = "CIDR-блоки, яким дозволено звертатись до публічного API EKS-кластера. ОБОВ'ЯЗКОВО вказати у terraform.tfvars."
  type        = list(string)
}
