import streamlit as st
import pandas as pd
import numpy as np
import datetime
import os
from io import BytesIO
import base64
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# Authentification (exemple simplifié)
import streamlit_authenticator as stauth

import ssl
# ssl_context = ssl.create_default_context()
# ssl_context.options |= ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1  # Désactive TLS 1.0 et 1.1

from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account

# ============================
# === CONFIGURATION GLOBALE ==
# ============================

# Pour un affichage plus adapté mobile
st.set_page_config(
    page_title="Gestion Achat/Vente",
    layout="wide",  # 'centered' ou 'wide'
    initial_sidebar_state="expanded"
)

# Récupération des e-mails autorisés depuis les secrets
ALLOWED_EMAILS = st.secrets["auth"]["allowed_emails"]

# ID du dossier Google Drive où stocker CSV et photos
GOOGLE_DRIVE_FOLDER_ID = "1dRCYxhWB15-dSpwklt1HAYJnc6zP5R7y"

# Nom du CSV principal
CSV_FILENAME = "stock.csv"
CSV_SALES_ACCOUNT_FILENAME = "comptes_de_vente.csv"

# Taux d'imposition
TAX_RATE = 0.126  # 12.6%

# =======================
# === FONCTIONS UTILES ===
# =======================

import ssl
from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account
from googleapiclient.discovery import build

import ssl
import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from googleapiclient.discovery import build

@st.cache_resource
def init_gdrive():
    """
    Initialise la connexion Google Drive via un compte de service avec un contexte SSL sécurisé.
    """
    # 🔒 Création d'un contexte SSL sécurisé
    ssl_context = ssl.create_default_context()
    ssl_context.options |= ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1  # Désactive TLS 1.0 et 1.1

    # 📜 Chargement des credentials du compte de service
    credentials = service_account.Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=["https://www.googleapis.com/auth/drive"]
    )

    # 🔄 Création d'une session avec le contexte SSL
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter()
    session.mount("https://", adapter)

    # 🔄 Application de la session aux credentials Google
    credentials.refresh(Request(session))  # Rafraîchit les tokens avec cette session

    # 📂 Création du service Google Drive avec les credentials mis à jour
    return build("drive", "v3", credentials=credentials)



def get_drive_file(service, filename):
    """
    Récupère un fichier Google Drive par son nom dans le dossier GOOGLE_DRIVE_FOLDER_ID.
    Retourne l'objet fichier Drive si trouvé, sinon None.
    """
    query = f"'{GOOGLE_DRIVE_FOLDER_ID}' in parents and name='{filename}' and trashed=false"
    
    try:
        results = service.files().list(q=query).execute()
        
        
        if isinstance(results, dict):  # Vérifier que la réponse est bien un dictionnaire
            files = results.get("files", [])
            return files[0] if files else None
        else:
            st.error("Erreur : La réponse de l'API n'est pas un dictionnaire. Vérifie GOOGLE_DRIVE_FOLDER_ID.")
            return None
    
    except Exception as e:
        st.error(f"Erreur lors de l'accès à Google Drive : {e}")
        return None



def download_csv_from_drive(service, filename):
    """
    Télécharge le CSV depuis Google Drive et retourne un DataFrame.
    """
    file_drive = get_drive_file(service, filename)
    if file_drive:
        request = service.files().get_media(fileId=file_drive['id'])
        csv_data = BytesIO(request.execute())
        return pd.read_csv(csv_data, sep=",")
    else:
        columns = ["id", "date_arrivee", "photo_id", "prix_achat", "description",
                   "taille", "collection", "estimation", "prix_vente", "date_vente",
                   "compte_vente", "gain_valeur", "gain_percent", "gain_apres_impots_valeur", "gain_apres_impots_percent"]
        return pd.DataFrame(columns=columns)

def upload_csv_to_drive(service, filename, df):
    """
    Mets à jour ou crée un fichier CSV sur Google Drive.
    """
    try:
        file_drive = get_drive_file(service, filename)
        csv_str = df.to_csv(index=False, encoding='utf-8')
        file_metadata = {"name": filename, "parents": [GOOGLE_DRIVE_FOLDER_ID]}
        media = MediaIoBaseUpload(BytesIO(csv_str.encode("utf-8")), mimetype="text/csv")

        if file_drive:
            service.files().update(fileId=file_drive['id'], media_body=media).execute()
        else:
            service.files().create(body=file_metadata, media_body=media).execute()
    except Exception as e:
        st.error(f"Erreur lors de l'upload du CSV : {e}")


def upload_photo_to_drive(service, photo_file):
    """
    Upload une photo sur Google Drive et retourne son ID.
    """
    file_metadata = {"name": photo_file.name, "parents": [GOOGLE_DRIVE_FOLDER_ID]}
    
    try:
        media = MediaIoBaseUpload(photo_file, mimetype=photo_file.type, resumable=True)
        file = service.files().create(body=file_metadata, media_body=media).execute()
        st.write(f"Upload terminé : {file['id']}")  # DEBUG
        return file['id']
    except Exception as e:
        st.error(f"Erreur lors de l'upload : {e}")
        return None

def get_drive_image_url(file_id, size=300):
    """Génère un lien Google Drive pour afficher une image avec la taille souhaitée."""
    return f"https://drive.google.com/thumbnail?id={file_id}&sz=w{size}"


def compute_gains(prix_achat, prix_vente, tax_rate=TAX_RATE):
    """
    Calcule le gain en valeur, en %, et après impôts.
    """
    gain_valeur = prix_vente - prix_achat
    gain_percent = (gain_valeur / prix_achat) * 100 if prix_achat != 0 else 0
    
    # Montant imposé = prix_vente * tax_rate
    # Gain après impôts = gain_valeur - (prix_vente * tax_rate)
    gain_apres_impots_valeur = gain_valeur - (prix_vente * tax_rate)
    gain_apres_impots_percent = (gain_apres_impots_valeur / prix_achat) * 100 if prix_achat != 0 else 0
    
    return gain_valeur, gain_percent, gain_apres_impots_valeur, gain_apres_impots_percent


def calculate_advanced_stats(df):
    """
    Calcule le temps moyen de rotation (en jours) et le volume des ventes par période.
    On se base sur la date_arrivee et la date_vente pour calculer.
    """
    # Temps moyen de rotation : moyenne de (date_vente - date_arrivee) sur les articles vendus
    df_vendus = df.dropna(subset=["date_vente", "prix_vente"])  # Garde uniquement ceux vendus
    if not df_vendus.empty:
        df_vendus["date_arrivee"] = pd.to_datetime(df_vendus["date_arrivee"])
        df_vendus["date_vente"] = pd.to_datetime(df_vendus["date_vente"])
        df_vendus["jours_stock"] = (df_vendus["date_vente"] - df_vendus["date_arrivee"]).dt.days
        temps_moyen_rotation = df_vendus["jours_stock"].mean()
    else:
        temps_moyen_rotation = 0

    # Volume des ventes par période (mois / trimestre)
    # Exemple : on groupe par trimestre
    if not df_vendus.empty:
        df_vendus["trimestre_vente"] = df_vendus["date_vente"].dt.to_period("Q")
        ventes_par_trimestre = df_vendus.groupby("trimestre_vente")["prix_vente"].sum().reset_index()
    else:
        ventes_par_trimestre = pd.DataFrame(columns=["trimestre_vente", "prix_vente"])

    # On renvoie les deux mesures
    return temps_moyen_rotation, ventes_par_trimestre


# =========================
# === AUTHENTIFICATION ===
# =========================

def user_authentication():
    """
    Exemple d'authentification simplifiée avec streamlit_authenticator,
    sur base d'adresses mail autorisées. 
    Dans un vrai setup, on ferait un OAuth Google complet.
    """
    # Simplifié : on propose juste un champ "Email" et on valide
    st.sidebar.title("Authentification")
    email = st.sidebar.text_input("Entrez votre email Google")
    login_button = st.sidebar.button("Se connecter")

    if "email_authenticated" not in st.session_state:
        st.session_state.email_authenticated = None
    
    if login_button:
        if email in ALLOWED_EMAILS:
            st.session_state.email_authenticated = email
        else:
            st.error("Email non autorisé !")

    return st.session_state.email_authenticated


# =========================
# === PAGES DE L'APPLI ===
# =========================

def page_ajout_article(drive, df_stock):
    st.title("Ajout d'un article au stock")
    
    photo_file = st.file_uploader("Photo de l'article", type=["png", "jpg", "jpeg"])
    prix_achat = st.number_input("Prix d'achat", min_value=0, step=1, format="%d")
    description = st.text_area("Description")
    taille = st.text_input("Taille")
    collection = st.text_input("Collection")
    estimation = st.number_input("Estimation (prix de vente estimé)", min_value=0, step=1, format="%d")
    
    if st.button("Enregistrer"):
        # Upload de la photo sur Drive (si une photo est présente)
        photo_id = None
        if photo_file is not None:
            # Il faut d'abord sauvegarder la photo en local (temporairement) pour SetContentFile
            with open(photo_file.name, "wb") as f:
                f.write(photo_file.getvalue())
            
            photo_id = upload_photo_to_drive(drive, photo_file)
            # On peut effacer le fichier local ensuite
            os.remove(photo_file.name)

        # Création d'un nouvel ID unique
        new_id = 1
        if not df_stock.empty:
            new_id = df_stock["id"].max() + 1
        
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        new_row = {
            "id": new_id,
            "date_arrivee": now_str,
            "photo_id": photo_id,
            "prix_achat": prix_achat,
            "description": description,
            "taille": taille,
            "collection": collection,
            "estimation": estimation,
            "prix_vente": np.nan,
            "date_vente": np.nan,
            "compte_vente": np.nan,
            "gain_valeur": np.nan,
            "gain_percent": np.nan,
            "gain_apres_impots_valeur": np.nan,
            "gain_apres_impots_percent": np.nan
        }
        
        df_stock = pd.concat([df_stock, pd.DataFrame([new_row])], ignore_index=True)


        # Upload CSV
        upload_csv_to_drive(drive, CSV_FILENAME, df_stock)
        st.success("Article ajouté avec succès !")
    
    return df_stock

def page_consultation_stock(drive, df_stock):
    st.title("Consultation du stock")

    # Filtres
    tailles_dispo = df_stock["taille"].dropna().unique().tolist()
    collections_dispo = df_stock["collection"].dropna().unique().tolist()


    # ✅ Ajout de la checkbox pour afficher uniquement les produits non vendus
    filter_non_vendu = st.checkbox("Afficher uniquement les produits non vendus", value=True)
    selected_taille = st.selectbox("Filtrer par taille", ["(Toutes)"] + tailles_dispo)
    selected_collection = st.selectbox("Filtrer par collection", ["(Toutes)"] + collections_dispo)
    search_description = st.text_input("Recherche (description contient)")

    # Appliquer les filtres
    df_filtered = df_stock.copy()
    if selected_taille != "(Toutes)":
        df_filtered = df_filtered[df_filtered["taille"] == selected_taille]
    if selected_collection != "(Toutes)":
        df_filtered = df_filtered[df_filtered["collection"] == selected_collection]
    if search_description:
        df_filtered = df_filtered[df_filtered["description"].str.contains(search_description, case=False, na=False)]
    # ✅ Appliquer le filtre "non vendu" si la checkbox est cochée
    if filter_non_vendu:
        df_filtered = df_filtered[df_filtered["prix_vente"].isna()]

    # 🔹 Ajouter les URLs d'images
    if "photo_id" in df_filtered.columns:
        df_filtered["Image"] = df_filtered["photo_id"].apply(get_drive_image_url)

    if df_filtered.empty:
        st.warning("Aucun article disponible.")
        return

    num_cols = 3  # Nombre d'articles par ligne
    cols = st.columns(num_cols)  # Création de colonnes

    for index, row in df_filtered.iterrows():
        col = cols[index % num_cols]  # Répartition équilibrée dans les colonnes
        with col:
            st.image(get_drive_image_url(row["photo_id"], size=700), use_container_width=True)  # Image de l'article
            st.markdown(f"**{row['description']}**")
            st.markdown(f"📏 **Taille :** {row['taille']}")
            st.markdown(f"👜 **Collection :** {row['collection']}")
            st.markdown(f"💰 **Prix Achat :** {row['prix_achat']} €")
            if pd.notna(row["prix_vente"]):
                st.markdown(f"💸 **Prix Vente :** {row['prix_vente']} €")

            # 🔹 Bouton "Fiche détaillée" pour changer de page
            if st.button(f"📄 Fiche détaillée {row['id']}", key=f"fiche_{row['id']}"):
                st.session_state.selected_article_id = row["id"]
                st.session_state.page = "Fiche détaillée"
                st.rerun()  # Redémarre l'affichage




    # # Sélection d'un article pour voir fiche détaillée
    # article_id = st.number_input("ID de l'article à consulter", min_value=0)
    # if st.button("Voir l'article"):
    #     if article_id in df_filtered["id"].values:
    #         article_details(drive, df_stock, article_id)
    #     else:
    #         st.error("Aucun article avec cet ID dans la liste filtrée.")

def article_details(drive, df_stock, article_id):
    """
    Affiche la page détaillée d'un article en deux colonnes :
    - 📷 À gauche : l'image
    - 📋 À droite : les détails
    """
    st.title(f"Fiche détaillée - Article ID {article_id}")

    df_article = df_stock[df_stock["id"] == article_id]
    if df_article.empty:
        st.error("Article introuvable.")
        return

    row = df_article.iloc[0]

    # 🔹 Mise en page en deux colonnes
    col1, col2 = st.columns([2, 2])  # Ajuste les proportions (1/3 - 2/3)

    with col1:
        # 📷 Affichage de l'image
        if pd.notna(row["photo_id"]):
            image_url = get_drive_image_url(row["photo_id"], size=700)  # Taille ajustable
            st.image(image_url, caption="Image de l'article", use_container_width=True)
        else:
            st.warning("Aucune image disponible.")

    with col2:
        # 📋 Détails du produit
        st.write(f"**💰 Prix d'achat :** {row['prix_achat']} €")
        st.write(f"**📄 Description :** {row['description']}")
        st.write(f"**📏 Taille :** {row['taille']}")
        st.write(f"**👜 Collection :** {row['collection']}")
        st.write(f"**💲 Estimation :** {row['estimation']} €")

    # # 🔙 Bouton de retour en bas
    # st.markdown("---")
    # if st.button("🔙 Retour au stock"):
    #     st.session_state.page = "Consultation stock"
    #     st.rerun()



    # 🔢 Calcul d'un prix de vente fictif
    st.write("## Calculer un gain fictif")
    prix_vente_fictif = st.number_input("Prix de vente fictif", min_value=0, step=1, format="%d")

    if st.button("Calculer le gain fictif"):
        try:
            gain_valeur, gain_percent, gain_imp_val, gain_imp_percent = compute_gains(row["prix_achat"], prix_vente_fictif)
            st.write(f"**Gain (valeur) :** {gain_valeur:.2f}")
            st.write(f"**Gain (%) :** {gain_percent:.2f}%")
            st.write(f"**Gain après impôts (valeur) :** {gain_imp_val:.2f}")
            st.write(f"**Gain après impôts (%) :** {gain_imp_percent:.2f}%")
        except Exception as e:
            st.error(f"Erreur lors du calcul du gain fictif : {e}")

    # ✅ Vérification du statut de vente
    st.write("## Déclarer l'article comme vendu")

    if pd.notna(row["prix_vente"]):
        st.warning("Cet article est déjà déclaré comme vendu.")
    else:
        prix_vente_reel = st.number_input("Prix de vente réel", min_value=0, step=1, format="%d")
        date_vente = st.date_input("Date de vente", datetime.date.today())

        # 🔍 Vérification du chargement des comptes de vente
        # Chargement du CSV des comptes de vente
        df_comptes = download_csv_from_drive(drive, CSV_SALES_ACCOUNT_FILENAME)
        
        # Vérifier si le DataFrame est vide ou si la colonne "compte" n'existe pas
        if df_comptes.empty or "compte" not in df_comptes.columns:
            # On crée un DataFrame par défaut
            default_comptes = [
                "vestiaire coco",
                "vestiaire ludo",
                "vestiaire carine",
                "vestiaire michelle",
                "vestiaire pro",
                "vestiaire persephone"
            ]
            df_comptes = pd.DataFrame({"compte": default_comptes})
            
            # On sauvegarde ce nouveau CSV sur Drive
            upload_csv_to_drive(drive, CSV_SALES_ACCOUNT_FILENAME, df_comptes)
            st.info("Aucun compte de vente n'était défini : un CSV par défaut a été créé.")
        
        # Maintenant, on peut directement utiliser df_comptes
        comptes_list = df_comptes["compte"].dropna().unique().tolist()
        compte_vente = st.selectbox("Compte de vente", comptes_list)


        # ✅ Bouton pour valider la vente
        if st.button("✅ Valider la vente"):
            try:
                # Calcul des gains
                gain_valeur, gain_percent, gain_imp_val, gain_imp_percent = compute_gains(row["prix_achat"], prix_vente_reel)

                # Mise à jour du DataFrame
                df_stock.loc[df_stock["id"] == article_id, "prix_vente"] = prix_vente_reel
                df_stock.loc[df_stock["id"] == article_id, "date_vente"] = str(date_vente)
                df_stock.loc[df_stock["id"] == article_id, "compte_vente"] = compte_vente
                df_stock.loc[df_stock["id"] == article_id, "gain_valeur"] = gain_valeur
                df_stock.loc[df_stock["id"] == article_id, "gain_percent"] = gain_percent
                df_stock.loc[df_stock["id"] == article_id, "gain_apres_impots_valeur"] = gain_imp_val
                df_stock.loc[df_stock["id"] == article_id, "gain_apres_impots_percent"] = gain_imp_percent

                # ✅ Enregistrer la mise à jour sur Google Drive
                upload_csv_to_drive(drive, CSV_FILENAME, df_stock)  # Correction ici !

                st.success("✅ Article mis à jour comme vendu !")
                st.balloons()  # Effet sympa après validation

            except Exception as e:
                st.error(f"❌ Erreur lors de l'enregistrement de la vente : {e}")




def page_statistiques(df_stock):
    st.title("Statistiques")
    
    # Nombre total d'articles
    total_articles = len(df_stock)
    
    # Nombre d'articles en stock (prix_vente NaN => pas encore vendu)
    df_en_stock = df_stock[df_stock["prix_vente"].isna()]
    nb_en_stock = len(df_en_stock)
    
    # Gain médian en % sur les articles vendus
    df_vendus = df_stock.dropna(subset=["prix_vente"])
    if not df_vendus.empty:
        gain_median_percent = df_vendus["gain_percent"].median()
    else:
        gain_median_percent = 0.0
    
    # Espérance de gain à venir = gain_median * valeur du stock
    # Valeur du stock = somme des prix d'achat (ou estimation ?)
    # A clarifier, on suppose somme des prix d'achat
    valeur_stock = df_en_stock["prix_achat"].sum()
    # Espérance = (gain_median en %) * valeur du stock / 100
    esperance_gain = (gain_median_percent / 100) * valeur_stock
    
    st.write(f"- **Nombre total d'articles :** {total_articles}")
    st.write(f"- **Nombre d'articles en stock :** {nb_en_stock}")
    st.write(f"- **Gain médian en % (articles vendus) :** {gain_median_percent:.2f}%")
    st.write(f"- **Valeur du stock (basée sur prix d'achat) :** {valeur_stock:.2f}")
    st.write(f"- **Espérance de gain à venir :** {esperance_gain:.2f}")

    # Analyse plus poussée (proposition #4)
    temps_moyen_rotation, ventes_par_trimestre = calculate_advanced_stats(df_stock)
    st.write(f"- **Temps moyen de rotation (jours) :** {temps_moyen_rotation:.2f}")
    
    st.write("### Volume des ventes par trimestre")
    if ventes_par_trimestre.empty:
        st.write("Aucune vente.")
    else:
        st.dataframe(ventes_par_trimestre)

    # Tableau récap des ventes par trimestre et compte de vente
    st.write("### Récap des ventes par trimestre et compte de vente")
    if not df_vendus.empty:
        df_vendus["date_vente"] = pd.to_datetime(df_vendus["date_vente"])
        df_vendus["trimestre_vente"] = df_vendus["date_vente"].dt.to_period("Q")
        
        recap = df_vendus.groupby(["trimestre_vente", "compte_vente"])["prix_vente"].sum().reset_index()
        st.dataframe(recap)
    else:
        st.write("Aucune vente pour le moment.")


def main():
    # Authentification utilisateur
    user_email = user_authentication()
    if not user_email:
        st.stop()
    else:
        st.sidebar.success(f"Connecté en tant que {user_email}")

    # Connexion à Google Drive
    drive = init_gdrive()

    # Charger le stock
    df_stock = download_csv_from_drive(drive, CSV_FILENAME)

    # 🔹 Vérifier si on doit afficher une fiche détaillée
    if "page" not in st.session_state:
        st.session_state.page = "Accueil"

    if st.session_state.page == "Fiche détaillée":
        article_details(drive, df_stock, st.session_state.selected_article_id)
        if st.button("🔙 Retour au stock"):
            st.session_state.page = "Consultation stock"
            st.rerun()
    else:
        # Menu latéral
        menu = ["Accueil", "Ajout article", "Consultation stock", "Statistiques"]
        choice = st.sidebar.selectbox("Menu", menu)

        if choice == "Accueil":
            st.title("Application de gestion Achat/Vente")
            st.write("Bienvenue ! Utilise le menu pour naviguer.")

        elif choice == "Ajout article":
            df_stock = page_ajout_article(drive, df_stock)

        elif choice == "Consultation stock":
            page_consultation_stock(drive, df_stock)

        elif choice == "Statistiques":
            page_statistiques(df_stock)



if __name__ == "__main__":
    main()
