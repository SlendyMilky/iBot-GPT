# Bot Discord d'Assistance IA 🤖🔧

Ce bot Discord utilise l'API OpenAI pour générer des réponses basées sur le contexte de chaque thread créé sur votre serveur Discord.

## Fonctionnalités 🚀

- Crée une réponse automatique basée sur le contenu de chaque nouveau thread.
- Enregistre l'historique des threads et des réponses générées.
- Permet de présenter le bot comme "jouer" à un jeu sur Discord.

## Prérequis 🧾

- Python installé sur votre machine.
- Une clé API OpenAI.
- Un token de bot Discord.

## Comment utiliser le bot 🤔

1. Clonez ce dépôt GitHub sur votre machine.

2. Définissez les variables d'environnement `Discord_Forum_Name`, `Discord_Bot_Token`, `GPT_KEY`.

3. Exécutez le code Python `bot.py`.

## Utilisation avec Docker 🐳

Si vous préférez utiliser Docker, vous pouvez exécuter le bot en utilisant `docker-compose`.

docker-compose.yml:

```yaml
version: '3.9'
    services:
        ibot-gpt:
            image: 'slendymilky/ibot-gpt:latest'
            container_name: ibot-gpt
            restart: always
            environment:
                - stack.env
```

Pour démarrer le bot avec Docker, exécutez la commande suivante :

```bash
docker-compose up -d
```


## Variables d'environnement 🔐

- `Discord_Forum_Name`: Le nom du serveur Discord sur lequel le bot fonctionne.
- `Discord_Bot_Token`: Le token d'authentification pour le bot Discord.
- `GPT_KEY`: La clé API pour l'API OpenAI.
- `GPT_MODEL`: Modèle gpt à utiliser. (gpt-3.5-turbo / gpt-4)

## Logging 📚

Le bot dispose d'un logging intégré qui enregistre chaque fois qu'un thread est créé et une réponse est générée. Les journaux sont stockés dans `thread_log.txt`.

---

**Remarque** : Ce bot a été conçu dans un but éducatif et de démonstration. Il a été conçu pour fonctionner dans un serveur appelé dans cette documentation `Discord_Forum_Name`. Ce n'est pas un centre d'aide professionnel mais un serveur communautaire.

Si vous avez des questions ou des améliorations, n'hésitez pas à ouvrir une issue ou une pull request.

Passez un bon temps à coder! 🎉🎨
