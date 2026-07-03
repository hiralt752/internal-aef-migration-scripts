from helpers.debug_logger import DebugLogger
logger = DebugLogger()
LANGUAGE_MAPPING = {
    "AR": "Arabic",
    "EN_CA": "English US",
    "EN_GB": "English GB",
    "EN_US": "English US",
    "FRA_FR": "French FR",
    "IND": "Indonesian",
    "SPA": "Spanish",
    "UZB": "Uzbek",
}

def languageMapper (language:str,q_id=None,q_type=None,lesson=None,filepath=None) -> str:
    if not language:
        logger.log(
            question_id=q_id,
            lesson=lesson,
            question_type=q_type,
            reason="LANGUAGE NOT PRESENT",
            file_path=filepath
        )
        return

    normalized_language = language.upper().strip()

    if LANGUAGE_MAPPING.get(normalized_language):
        return LANGUAGE_MAPPING.get(normalized_language)

    logger.log(
        question_id=q_id,
        lesson=lesson,
        question_type=q_type,
        reason=f'Additional language found {language}',
        file_path=filepath
    ) 
    return
