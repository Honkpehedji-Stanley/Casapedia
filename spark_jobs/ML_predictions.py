import os
from datetime import datetime

from pyspark.ml import Pipeline
from pyspark.ml.feature import Imputer, OneHotEncoder, StringIndexer, VectorAssembler
from pyspark.ml.regression import LinearRegression
from pyspark.sql import SparkSession
from pyspark.sql.functions import avg, coalesce, col, count, month, to_date, trim, year

S3_BUCKET = os.getenv("CASAPEDIA_S3_BUCKET", "casapedia-datalake")
PROCESSED_DIR = f"s3a://{S3_BUCKET}/processed"


def log_step(message):
    print(f"[{datetime.utcnow().isoformat(timespec='seconds')}] {message}")


def write_clean_parquet(df, path):
    log_step(f"Ecriture parquet vers {path}...")
    df.write.mode("overwrite").parquet(path)
    log_step(f"Ecriture terminee pour {path}")


def main():
    transactions_path = os.environ.get("CASAPEDIA_TRANSACTIONS_INPUT", f"{PROCESSED_DIR}/transactions/transactions.jsonl")
    communes_path = os.environ.get("CASAPEDIA_COMMUNES_INPUT", f"{PROCESSED_DIR}/communes/communes.jsonl")
    demographics_path = os.environ.get("CASAPEDIA_DEMOGRAPHICS_INPUT", f"{PROCESSED_DIR}/demographics/demographics.jsonl")
    density_path = os.environ.get("CASAPEDIA_DENSITY_INPUT", f"{PROCESSED_DIR}/demographics/density.jsonl")
    unemployment_path = os.environ.get("CASAPEDIA_CHOMAGE_INPUT", f"{PROCESSED_DIR}/demographics/chomage_commune.jsonl")
    dpe_path = os.environ.get("CASAPEDIA_DPE_INPUT", f"{PROCESSED_DIR}/dpe/dpe.jsonl")
    output_root = os.environ.get("CASAPEDIA_ML_OUTPUT", f"{PROCESSED_DIR}/ml_predictions")

    log_step("Initialisation de SparkSession pour le job ML...")
    spark = SparkSession.builder.appName("Casapedia_ML_Predictions").getOrCreate()

    log_step(f"Lecture transactions depuis {transactions_path}")
    transactions = spark.read.json(transactions_path)
    log_step(f"Lecture communes depuis {communes_path}")
    communes = spark.read.json(communes_path)
    log_step(f"Lecture demographics depuis {demographics_path}")
    demographics = spark.read.json(demographics_path)

    def read_optional_json(path, schema_definition):
        try:
            return spark.read.json(path)
        except Exception:
            return spark.createDataFrame([], schema_definition)

    log_step(f"Lecture density depuis {density_path}")
    density = read_optional_json(density_path, "commune_id string, densite_population double")
    log_step(f"Lecture unemployment depuis {unemployment_path}")
    unemployment = read_optional_json(unemployment_path, "commune_id string, taux_chomage double")

    try:
        log_step(f"Lecture DPE depuis {dpe_path}")
        dpe = spark.read.json(dpe_path)
        dpe_agg = dpe.groupBy("commune_id").agg(
            avg("emissions_co2").alias("avg_emissions_co2"),
            avg("consommation_energie").alias("avg_consumption_energie"),
            count("id").alias("dpe_volume"),
        )
    except Exception:
        dpe_agg = spark.createDataFrame([], "commune_id string, avg_emissions_co2 double, avg_consumption_energie double, dpe_volume long")

    log_step("Construction des features communes")
    communes_features = communes.select(
        trim(col("code_insee")).alias("commune_id"),
        col("latitude").cast("double").alias("latitude"),
        col("longitude").cast("double").alias("longitude"),
    )

    log_step("Construction des features demographics")
    demographics_features = demographics.select(
        trim(col("commune_id")).alias("commune_id"),
        col("population").cast("double").alias("population"),
    )

    log_step("Construction des features density")
    density_features = density.select(
        trim(col("commune_id")).alias("commune_id"),
        col("densite_population").cast("double").alias("densite_population"),
    ).groupBy("commune_id").agg(
        avg("densite_population").alias("densite_population"),
    )

    log_step("Construction des features chômage")
    unemployment_features = unemployment.select(
        trim(col("commune_id")).alias("commune_id"),
        col("taux_chomage").cast("double").alias("taux_chomage"),
    ).groupBy("commune_id").agg(
        avg("taux_chomage").alias("taux_chomage"),
    )

    log_step("Construction du jeu d'entrainement")
    training_base = transactions.select(
        trim(col("commune_id")).alias("commune_id"),
        coalesce(
            to_date(trim(col("date_transaction")), "yyyy-MM-dd"),
            to_date(trim(col("date_transaction")), "dd/MM/yyyy"),
            to_date(trim(col("date_transaction")), "yyyyMMdd"),
        ).alias("date_transaction"),
        trim(col("type_bien")).alias("type_bien"),
        col("surface").cast("double").alias("surface"),
        col("prix").cast("double").alias("prix"),
        col("prix_m2").cast("double").alias("prix_m2"),
        col("nombre_pieces").cast("double").alias("nombre_pieces"),
        trim(col("code_postal")).alias("code_postal"),
    ).where(col("prix_m2").isNotNull() & (col("prix_m2") > 0) & col("surface").isNotNull())

    log_step("Jointures des jeux de contexte")
    training = training_base.join(communes_features, on="commune_id", how="left") \
        .join(demographics_features, on="commune_id", how="left") \
        .join(density_features, on="commune_id", how="left") \
        .join(unemployment_features, on="commune_id", how="left") \
        .join(dpe_agg, on="commune_id", how="left")

    log_step("Ajout des variables temporelles")
    training = training.withColumn("transaction_year", year(col("date_transaction"))) \
        .withColumn("transaction_month", month(col("date_transaction")))

    numeric_columns = [
        "surface",
        "nombre_pieces",
        "latitude",
        "longitude",
        "population",
        "densite_population",
        "taux_chomage",
        "avg_emissions_co2",
        "avg_consumption_energie",
        "dpe_volume",
        "transaction_year",
        "transaction_month",
    ]

    imputer = Imputer(
        inputCols=numeric_columns,
        outputCols=[f"{column_name}_imputed" for column_name in numeric_columns],
    )
    type_indexer = StringIndexer(inputCol="type_bien", outputCol="type_bien_index", handleInvalid="keep")
    type_encoder = OneHotEncoder(inputCols=["type_bien_index"], outputCols=["type_bien_vector"])

    assembled_features = [f"{column_name}_imputed" for column_name in numeric_columns] + ["type_bien_vector"]
    assembler = VectorAssembler(inputCols=assembled_features, outputCol="features")
    regressor = LinearRegression(featuresCol="features", labelCol="prix_m2", predictionCol="predicted_prix_m2")

    pipeline = Pipeline(stages=[imputer, type_indexer, type_encoder, assembler, regressor])

    log_step("Découpage train/test")
    train_df, test_df = training.randomSplit([0.8, 0.2], seed=42)
    log_step("Entraînement du modèle MLlib")
    model = pipeline.fit(train_df)
    log_step("Génération des prédictions sur le jeu de test")
    scored = model.transform(test_df)

    predictions = scored.select(
        "commune_id",
        "date_transaction",
        "type_bien",
        "surface",
        "prix",
        "prix_m2",
        "predicted_prix_m2",
        "latitude",
        "longitude",
        "population",
        "densite_population",
        "taux_chomage",
        "avg_emissions_co2",
        "avg_consumption_energie",
        "dpe_volume",
    )

    metrics = model.stages[-1].summary
    metrics_df = spark.createDataFrame(
        [
            (
                float(metrics.rootMeanSquaredError),
                float(metrics.meanAbsoluteError),
                float(metrics.r2),
            )
        ],
        ["rmse", "mae", "r2"],
    )

    output_path = f"{output_root}/predictions"
    metrics_path = f"{output_root}/metrics"
    model_path = f"{output_root}/model"

    log_step("Ecriture des prédictions")
    write_clean_parquet(predictions, output_path)
    log_step("Ecriture des métriques")
    write_clean_parquet(metrics_df, metrics_path)

    log_step("Sauvegarde du modele")
    model.write().overwrite().save(model_path)

    log_step("Job ML terminé avec succès.")
    spark.stop()


if __name__ == "__main__":
    main()