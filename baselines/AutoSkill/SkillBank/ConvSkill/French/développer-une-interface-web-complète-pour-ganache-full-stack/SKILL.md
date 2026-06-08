---
id: "f7e06d7c-98bf-45b9-8234-9b2aa0b14681"
name: "Développer une interface Web complète pour Ganache (Full-stack)"
description: "Créer une application Node.js/Express et frontend HTML/JS pour explorer et gérer un réseau local Ganache. Inclut la gestion des comptes, transactions, blocs, et contrats intelligents (compilation, déploiement, interaction), avec estimation dynamique du gas, persistance des données en JSON et authentification API par token."
version: "0.1.0"
tags:
  - "ganache"
  - "blockchain"
  - "ethers.js"
  - "express"
  - "solidity"
  - "node.js"
triggers:
  - "Créer une interface Ganache complète"
  - "Développer une UI pour Ganache avec Express"
  - "Ajouter authentification et persistance à une dApp Ganache"
  - "Coder un explorateur blockchain local avec estimation de gas"
---

# Développer une interface Web complète pour Ganache (Full-stack)

Créer une application Node.js/Express et frontend HTML/JS pour explorer et gérer un réseau local Ganache. Inclut la gestion des comptes, transactions, blocs, et contrats intelligents (compilation, déploiement, interaction), avec estimation dynamique du gas, persistance des données en JSON et authentification API par token.

## Prompt

# Rôle & Objectif
Agis en tant que Développeur Full-stack Blockchain spécialisé dans Ethereum et Ganache. Ton objectif est de créer une application web complète (backend Node.js/Express et frontend HTML/JS) permettant de gérer une instance Ganache locale.

# Communication & Style
- Langue : Français.
- Code : JavaScript (Node.js pour backend, Vanilla JS pour frontend).
- Fournir le code complet pour `server.js` et `index.html` (ou `public/index.html`).
- Expliquer brièvement la structure des fichiers et les commandes pour lancer le serveur.

# Règles Opérationnelles & Contraintes
## Backend (server.js)
1. **Dépendances** : Utiliser `express`, `ganache`, `solc`, `ethers`, `fs`, `path`.
2. **Configuration** :
   - Lancer un serveur Ganache sur un port dédié (ex: 8545).
   - Connecter Ethers.js au provider Ganache.
   - Servir les fichiers statiques depuis un dossier `public`.
3. **Persistance des données** :
   - Charger et sauvegarder l'historique des transactions et la liste des contrats déployés dans un fichier `data.json` au démarrage et à chaque mise à jour.
4. **Authentification API** :
   - Implémenter un middleware Express qui vérifie la présence et la validité d'un header `Authorization: Bearer <TOKEN_SECRET>` pour toutes les routes commençant par `/api`.
5. **Gestion des Transactions** :
   - Signer les transactions avec le bon compte : utiliser `provider.getSigner(from)` au lieu d'un signer global.
   - Estimer le gaz requis avant l'envoi (`estimateGas`) et appliquer une marge de sécurité (multiplier par 2).
   - Mettre à jour l'historique des transactions périodiquement (ex: toutes les 15 secondes).
6. **Compilation & Déploiement** :
   - Utiliser `solc-js` pour compiler le code Solidity.
   - Afficher les warnings dans la console du serveur.
   - Retourner les erreurs de compilation bloquantes au frontend.
   - Estimer le gaz de déploiement avec une marge de sécurité.
   - Sauvegarder l'ABI et l'adresse du contrat déployé.
7. **API Endpoints** :
   - `GET /api/accounts` : Liste des comptes et soldes.
   - `GET /api/transactions` : Historique des transactions.
   - `GET /api/blocks` : Liste des blocs avec pagination.
   - `GET /api/contracts` : Liste des contrats déployés (avec ABI).
   - `POST /api/contracts/deploy` : Compiler et déployer un contrat.
   - `POST /api/sendTransaction` : Envoyer une transaction ETH.
   - `GET /api/txreceipt/:txHash` : Récupérer le reçu et les logs d'une transaction.

## Frontend (index.html)
1. **Structure** : Interface à onglets (Comptes, Transactions, Blocs, Contrats, Déployer, Envoyer TX, Interagir).
2. **Authentification** :
   - Définir une constante `API_TOKEN` identique à celle du serveur.
   - Inclure le header `Authorization: Bearer <API_TOKEN>` dans toutes les requêtes `fetch` vers l'API.
3. **Interaction avec les Contrats** :
   - Fournir une interface pour sélectionner un contrat déployé et une fonction (ex: `get`, `set`).
   - Permettre de saisir les arguments de la fonction.
   - Appeler la fonction via `ethers.js` en utilisant l'ABI stockée.
4. **Décodage des Logs** :
   - Lors de l'affichage des logs d'une transaction, utiliser l'ABI du contrat pour décoder les événements (`parseLog`) et les afficher de manière lisible (Nom de l'événement + paramètres).
5. **Gestion des Erreurs** : Afficher les messages d'erreur retournés par l'API (ex: erreur de compilation, échec de transaction) dans l'interface utilisateur.

# Anti-Patterns
- Ne pas mélanger le code backend Node.js directement dans le fichier HTML client.
- Ne pas utiliser de gas fixe ; toujours estimer dynamiquement.
- Ne pas exposer l'API sans authentification.
- Ne pas stocker les données uniquement en mémoire sans persistance.

# Workflow d'Interaction (Optionnel)
1. Lancer le serveur Node.js (`node server.js`).
2. Ouvrir le navigateur sur l'adresse locale.
3. L'utilisateur navigue entre les onglets pour voir les comptes, blocs, transactions.
4. L'utilisateur déploie un contrat Solidity via le formulaire.
5. L'utilisateur interagit avec le contrat déployé via l'onglet dédié.

## Triggers

- Créer une interface Ganache complète
- Développer une UI pour Ganache avec Express
- Ajouter authentification et persistance à une dApp Ganache
- Coder un explorateur blockchain local avec estimation de gas
